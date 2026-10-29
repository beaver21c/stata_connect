"""도구 동작 구현 — 실행 흐름: guard(정적 검사) → 고유값 점검 → 실행 → 출력 필터 → 사용 기록.

MCP 프로토콜과 분리해 단위 테스트가 가능하도록 함(server.py는 얇은 연결부).
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .backends import Backend, BatchBackend, RunOutcome, select_backend
from .backends.base import stata_path
from .config import Settings
from .discovery import (
    DiscoveryReport,
    StataInstall,
    choose_installation,
    com_registration,
    discover,
    run_about,
    scan_installations,
    version_declaration,
)
from .dofile import (
    MASTER_NAME,
    DoFile,
    DoFileError,
    backup_file,
    ensure_master_includes,
    new_dofile,
    section_run_code,
    validate_filename,
)
from .editor_sync import EditorSync
from .guard.command_policy import ACTION_LABEL, Action, CommandGuard, GuardContext, GuardResult, default_file_reader
from .guard.output_filter import FilterConfig, extract_markers, filter_output
from .guard.stata_lexer import iter_statements, parse_command, abbrev_match
from .log_compare import compare_logs
from .project import init_project
from .session_log import SessionLog, disclosure_draft


@dataclass
class ToolResult:
    text: str
    is_error: bool = False


class ServiceError(Exception):
    pass


# ── Stata 코드 생성(표지 출력 방식) ─────────────────────────────
# 숫자 서식 %24.0g: 폭 24에서 자릿수 자동 선택(Stata 서식 규칙 기준, 실기 확인 필요)

SCHEMA_CODE = """\
display "SASCHEMA|N|" _N
display "SASCHEMA|K|" c(k)
if c(k) > 0 {
    foreach __sav of varlist _all {
        local __sat : type `__sav'
        local __savl : value label `__sav'
        local __sal : variable label `__sav'
        quietly count if missing(`__sav')
        display `"SAVAR|`__sav'|`__sat'|`__savl'|`r(N)'|`__sal'"'
    }
}
"""


def uniqueness_probe_code(tokens: list[str]) -> str:
    varlist = " ".join(tokens)
    return f"""\
capture unab __saul : {varlist}
if !_rc {{
    foreach __sauv of local __saul {{
        tempvar __saut
        quietly egen `__saut' = tag(`__sauv')
        quietly count if `__saut' & !missing(`__sauv')
        local __sauu = r(N)
        quietly count if !missing(`__sauv')
        display "SAUNIQ|`__sauv'|`__sauu'|" r(N)
        drop `__saut'
    }}
}}
"""


_RESULT_NAME_RE = re.compile(
    r"^(?:[rec]\([A-Za-z_][\w]*\)|_(?:b|se)\[[A-Za-z0-9_.#:~]+\]|[A-Za-z_]\w{0,31})$"
)


def results_code(names: list[str]) -> str:
    lines = []
    for name in names:
        expr = name if not re.fullmatch(r"[A-Za-z_]\w*", name) else f"scalar({name})"
        lines.append(f'capture noisily display "SARES|{name}|" %24.0g ({expr})')
        if re.fullmatch(r"[rec]\(\w+\)", name):  # 문자열 저장결과 대비
            lines.append(f'if _rc display `"SARES|{name}|`{name}\'"\'')
    return "\n".join(lines) + "\n"


_NEWVAR_RE = re.compile(
    r"^(?:(?:byte|int|long|float|double|str\d+|strL)\s+)?([A-Za-z_]\w*)\s*=", re.IGNORECASE
)
_DATA_RELOAD = (("use", "u"), ("sysuse", "sysuse"), ("webuse", "webuse"), ("merge", "merge"), ("append", "append"),
                ("import", "import"), ("insheet", "insheet"), ("infile", "infile"), ("reshape", "reshape"),
                ("collapse", "collapse"), ("joinby", "joinby"), ("clear", "clear"), ("contract", "contract"),
                ("cross", "cross"), ("frame", "frame"))


class StataAgentService:
    def __init__(self, settings: Settings | None = None, backend: Backend | None = None,
                 batch: BatchBackend | None = None, discovery_report: DiscoveryReport | None = None):
        self.settings = settings or Settings.from_env()
        self._discovery = discovery_report
        if backend is None:
            exe = self.settings.stata_exe or self._quick_exe()
            backend, self.backend_reason = select_backend(self.settings.backend, exe)
        else:
            self.backend_reason = "외부 지정"
        self.backend = backend
        self.batch = batch or BatchBackend(self.settings.stata_exe or self._quick_exe(), self.settings.batch_timeout)
        self.editor = EditorSync(self.backend, self.settings.editor)
        self.filter_cfg = FilterConfig(max_chars=self.settings.max_output_chars,
                                       mask_small_cells=self.settings.mask_small_cells)
        self.project_root: Path | None = None
        self.session_id: str | None = None
        self.variables: set[str] | None = None
        self.version_line = f"version {self.settings.stata_version}" if self.settings.stata_version else None
        self.log: SessionLog | None = None
        self.last_log_path: Path | None = None

    # ── 탐지 ──
    def _quick_exe(self) -> str | None:
        inst = self._selected_install(full=False)
        return inst.exe if inst else None

    def _selected_install(self, full: bool) -> StataInstall | None:
        if self._discovery is None or (full and not any(i.about for i in self._discovery.installs)):
            if full:
                self._discovery = discover(run_about_checks=True, preferred_exe=self.settings.stata_exe)
            else:
                installs = scan_installations()
                self._discovery = DiscoveryReport(
                    installs, choose_installation(installs, self.settings.stata_exe), com_registration(),
                    self.settings.stata_exe)
        rep = self._discovery
        if rep.com.registered and rep.com.server_path and getattr(self, "backend", None) is not None \
                and self.backend.name == "com_gui":
            for inst in rep.installs:
                if inst.exe.lower() == rep.com.server_path.lower():
                    return inst
        return rep.selected

    def _version_line(self) -> str:
        if not self.version_line:
            self.version_line = version_declaration(self._selected_install(full=False))
        return self.version_line

    # ── 공통 도우미 ──
    def _require_project(self) -> Path:
        if self.project_root is None:
            raise ServiceError("프로젝트 세션 없음 → stata_open_session(project_dir)을 먼저 호출")
        return self.project_root

    def _project_file(self, filename: str) -> Path:
        root = self._require_project()
        name = str(filename or "").strip()
        if not name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ServiceError(f"프로젝트 폴더 기준 상대 파일명만 허용: {filename}")
        path = (root / name).resolve()
        if root.resolve() not in path.parents and path != root.resolve():
            raise ServiceError(f"프로젝트 폴더 밖 경로 거부: {filename}")
        return path

    def _guard(self, code: str) -> GuardResult:
        root = self._require_project()
        ctx = GuardContext(
            project_root=str(root),
            known_variables=frozenset(self.variables) if self.variables else None,
            read_file=default_file_reader,
        )
        return CommandGuard(ctx).check_code(code)

    def _record(self, tool: str, **fields) -> None:
        if self.log is not None:
            self.log.record(tool, session_id=self.session_id, backend=self.backend.name, **fields)

    def _filtered(self, outcome: RunOutcome) -> tuple[str, list]:
        res = filter_output(outcome.log_text, self.filter_cfg, str(outcome.log_path) if outcome.log_path else None)
        return res.text, res.events

    def _save_last_log(self, outcome: RunOutcome) -> None:
        root = self._require_project()
        dest = root / ".stata-agent" / "last_run.log"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(outcome.log_text or "", encoding="utf-8")
        self.last_log_path = dest

    def _strip_markers(self, text: str) -> str:
        return "\n".join(
            ln for ln in text.splitlines()
            if not re.match(r"^\s*(SA[A-Z0-9]+\|)", ln.strip()) and "SAVAR|" not in ln and "SASCHEMA|" not in ln
        )

    def _run_internal(self, code: str) -> RunOutcome:
        root = self._require_project()
        return self.backend.run_code(code, self.session_id or "", root)

    # ── 고유값 점검(식별자 성격 변수) ──
    def _identifier_check(self, guard: GuardResult) -> list[dict]:
        if not guard.identifier_vars or not self.backend.persistent_session:
            return []
        outcome = self._run_internal(uniqueness_probe_code(guard.identifier_vars))
        flagged = []
        for fields in extract_markers(outcome.log_text, "SAUNIQ"):
            if len(fields) < 3:
                continue
            name, uniq, nonmiss = fields[0], fields[1], fields[2]
            try:
                u, n = int(float(uniq)), int(float(nonmiss))
            except ValueError:
                continue
            ratio = (u / n) if n else 0.0
            if n and ratio > self.settings.unique_ratio:
                flagged.append({"variable": name, "unique": u, "nonmissing": n, "ratio": round(ratio, 3)})
        return flagged

    def _update_variables_from_code(self, code: str) -> bool:
        """코드로 생긴 새 변수를 캐시에 추가. 자료 교체 명령이 있으면 True(스키마 재조회 필요)."""
        reload_needed = False
        for st in iter_statements(code):
            if st.context != "stata":
                continue
            cmd = parse_command(st.text)
            if any(abbrev_match(cmd.name, full, mn) for full, mn in _DATA_RELOAD):
                reload_needed = True
            if self.variables is None:
                continue
            if abbrev_match(cmd.name, "generate", "g") or cmd.name == "egen":
                m = _NEWVAR_RE.match(cmd.args)
                if m:
                    self.variables.add(m.group(1))
            elif abbrev_match(cmd.name, "rename", "ren"):
                parts = cmd.args.split()
                if len(parts) >= 2:
                    self.variables.discard(parts[0])
                    self.variables.add(parts[1])
        return reload_needed

    def _refresh_variables(self) -> dict | None:
        if not self.backend.persistent_session:
            return None
        outcome = self._run_internal(SCHEMA_CODE)
        schema = parse_schema(outcome.log_text)
        if schema is not None:
            self.variables = {v["name"] for v in schema["variables"]}
        return schema

    # ── 실행 공통 흐름 ──
    def _guarded_run(self, tool: str, code_for_guard: str, runner, acknowledge: bool, **record) -> ToolResult:
        guard = self._guard(code_for_guard)
        if guard.blocked:
            self._record(tool, status="blocked", guard_action=ACTION_LABEL[guard.action],
                         guard_rules=sorted({f.rule for f in guard.findings}), **record)
            return ToolResult(
                "실행하지 않음 — 원자료 보호 규칙에 따라 차단\n" + guard.summary()
                + "\n→ 차단 명령을 제외하거나 대체 명령으로 수정할 것. 꼭 필요하면 연구자가 Stata 창에서 직접 실행.",
                True,
            )
        if guard.needs_approval and not acknowledge:
            self._record(tool, status="needs_approval", guard_action=ACTION_LABEL[guard.action],
                         guard_rules=sorted({f.rule for f in guard.findings}), **record)
            return ToolResult(
                "실행 보류 — 연구자 확인 필요\n" + guard.summary()
                + "\n→ 연구자에게 위 사유를 설명하고 동의를 받은 경우에만 acknowledge_risks=true로 다시 요청.",
                True,
            )
        flagged = [] if acknowledge else self._identifier_check(guard)
        if flagged:
            self._record(tool, status="needs_approval", guard_action="승인 필요", guard_rules=["G14"], **record)
            desc = ", ".join(f"{f['variable']}(고유값 {f['ratio']:.0%})" for f in flagged)
            return ToolResult(
                f"실행 보류 — 식별자 성격 변수의 빈도·고유값 출력: {desc}\n"
                "→ 개별 값이 그대로 노출될 수 있음. 범주화·요약통계로 바꾸거나, 연구자 동의 시 acknowledge_risks=true.",
                True,
            )
        outcome: RunOutcome = runner()
        if self.project_root is not None and outcome.log_text:
            self._save_last_log(outcome)
        text, events = self._filtered(outcome)
        if self._update_variables_from_code(code_for_guard) and outcome.ok:
            self._refresh_variables()
        status = "ok" if outcome.ok else "error"
        self._record(tool, status=status, return_code=outcome.return_code,
                     guard_action=ACTION_LABEL[guard.action],
                     guard_rules=sorted({f.rule for f in guard.findings}) or None,
                     blocked_output=[e.reason for e in events] or None,
                     acknowledged_risks=acknowledge or None, **record)
        head = [f"{'✅ 실행 완료' if outcome.ok else '❌ 실행 오류'} (return code {outcome.return_code})"]
        if outcome.message:
            head.append(outcome.message)
        warn = [f for f in guard.findings if f.action >= Action.WARN]
        if warn:
            head.append(guard.summary())
        if events:
            head.append(f"출력 필터 차단 {len(events)}건: " + "; ".join(e.reason for e in events))
        return ToolResult("\n".join(head) + "\n\n=== Stata 출력(필터 적용) ===\n" + (text or "(출력 없음)"),
                          not outcome.ok)

    # ══ 도구 ══════════════════════════════════════════════════════
    def status(self, refresh: bool = False) -> ToolResult:
        if refresh:
            self._discovery = None
        inst = self._selected_install(full=bool(refresh))
        data = {
            "server_version": __version__,
            "backend": self.backend.status(),
            "backend_reason": self.backend_reason,
            "batch_backend": self.batch.status(),
            "project": str(self.project_root) if self.project_root else None,
            "session_id": self.session_id,
            "version_line": self.version_line,
            "selected_stata": inst.public_dict() if inst else None,
            "discovery": self._discovery.public_dict() if self._discovery else None,
            "variables_cached": len(self.variables) if self.variables is not None else None,
            "settings": {
                "max_output_chars": self.settings.max_output_chars,
                "mask_small_cells": self.settings.mask_small_cells,
                "unique_ratio": self.settings.unique_ratio,
                "editor": self.settings.editor,
            },
        }
        if not refresh:
            data["note"] = "라이선스 만료일은 refresh=true일 때 about 배치 실행으로 확인"
        return ToolResult(json.dumps(data, ensure_ascii=False, indent=2))

    def open_session(self, project_dir: str, session_id: str | None = None) -> ToolResult:
        root = Path(project_dir).expanduser()
        if not root.is_dir():
            return ToolResult(f"프로젝트 폴더 없음: {project_dir} (폴더를 먼저 만들 것)", True)
        root = root.resolve()
        sid = re.sub(r"[^A-Za-z0-9_.-]+", "_", session_id or root.name).strip("_") or "stata_session"
        version_line = self._version_line()
        created = init_project(root, version_line)
        outcome = self.backend.open_session(root, sid)
        if not outcome.ok:
            return ToolResult("세션 열기 실패: " + (outcome.message or "원인 미상"), True)
        self.project_root, self.session_id = root, sid
        self.variables = None
        self.log = SessionLog(root)
        self._record("stata_open_session", status="ok")
        lines = [
            f"✅ 세션 준비: {sid} ({self.backend.name}, {self.backend_reason})",
            f"프로젝트: {root}",
            f"do-file 버전 선언: {version_line}",
        ]
        if not self.backend.persistent_session:
            lines.append("⚠️ 배치 모드: 호출 간 메모리 미유지 → 각 섹션에 자료 불러오기 포함 필요, 편집기 연동 불가")
        if created:
            lines.append("생성한 규약 파일·폴더: " + ", ".join(created))
        ver = extract_markers(outcome.log_text, "SA_VERSION")
        if ver:
            lines.append(f"Stata 버전(c(stata_version)): {ver[0][0]}")
        return ToolResult("\n".join(lines))

    def load_data(self, path: str) -> ToolResult:
        root = self._require_project()
        if path.lower().startswith("sysuse:"):
            name = path.split(":", 1)[1].strip()
            if not re.fullmatch(r"[A-Za-z0-9_]+", name):
                return ToolResult("sysuse 자료명 형식 오류", True)
            load = f"sysuse {name}, clear"
        else:
            p = Path(path)
            p = p if p.is_absolute() else (root / p)
            if not p.is_file():
                return ToolResult(f"자료 파일 없음: {path}", True)
            if p.suffix.lower() != ".dta":
                return ToolResult("stata_load_data는 .dta만 지원 → 다른 형식은 import 명령을 섹션에 작성", True)
            load = f'use "{stata_path(p)}", clear'
        outcome = self._run_internal(f"{load}\ndescribe, short\n{SCHEMA_CODE}")
        if not outcome.ok:
            self._record("stata_load_data", status="error", return_code=outcome.return_code)
            text, _ = self._filtered(outcome)
            return ToolResult("자료 불러오기 실패\n" + self._strip_markers(text), True)
        schema = parse_schema(outcome.log_text)
        if schema:
            self.variables = {v["name"] for v in schema["variables"]}
        self._record("stata_load_data", status="ok")
        n = schema["N"] if schema else "?"
        k = schema["K"] if schema else "?"
        return ToolResult(f"✅ 자료 불러옴: 관측치 {n}개, 변수 {k}개 (값은 반환하지 않음 → 구조는 stata_schema)")

    def schema(self) -> ToolResult:
        self._require_project()
        if not self.backend.persistent_session:
            return ToolResult("배치 모드에서는 현재 자료가 메모리에 없음 → 섹션 코드에 자료 불러오기 포함", True)
        schema = self._refresh_variables()
        self._record("stata_schema", status="ok" if schema else "error")
        if schema is None:
            return ToolResult("스키마 조회 실패(자료가 불러와져 있는지 확인)", True)
        return ToolResult(json.dumps(schema, ensure_ascii=False, indent=2))

    def write_dofile(self, filename: str, sections: list[dict], author: str | None = None,
                     overwrite: bool = False) -> ToolResult:
        root = self._require_project()
        try:
            validate_filename(filename)
            path = self._project_file(filename)
            if path.exists() and not overwrite:
                return ToolResult(f"이미 있는 파일: {filename} → stata_patch_dofile 사용(또는 overwrite=true)", True)
            pairs = [(str(s.get("title", "")), str(s.get("code", ""))) for s in sections or []]
            if not pairs:
                return ToolResult("sections가 비어 있음", True)
            content = new_dofile(filename, pairs, self._version_line(), author or "AI")
        except (DoFileError, ServiceError) as e:
            return ToolResult(str(e), True)
        bak = backup_file(path, root)
        path.write_text(content, encoding="utf-8")
        master = root / MASTER_NAME
        master.write_text(
            ensure_master_includes(master.read_text(encoding="utf-8") if master.is_file() else None,
                                   filename, self._version_line()), encoding="utf-8")
        guard = self._guard(content)
        shown = self.editor.show(path, self.session_id or "")
        self._record("stata_write_dofile", file=filename, status="ok", backup=str(bak) if bak else None,
                     guard_action=ACTION_LABEL[guard.action])
        lines = [f"✅ 작성: {filename} (섹션 {len(pairs)}개, 00_master.do 갱신)"]
        if bak:
            lines.append(f"기존 파일 백업: {bak.name}")
        if guard.findings:
            lines.append("실행 전 참고 — " + guard.summary())
        lines.append(f"편집기: {shown.message}")
        return ToolResult("\n".join(lines))

    def patch_dofile(self, filename: str, action: str, section_id: str | None = None, title: str | None = None,
                     code: str | None = None, after: str | None = None) -> ToolResult:
        root = self._require_project()
        try:
            path = self._project_file(filename)
            if not path.is_file():
                return ToolResult(f"파일 없음: {filename} → stata_write_dofile로 먼저 작성", True)
            doc = DoFile.parse(path.read_text(encoding="utf-8"))
            if action == "add":
                sec = doc.add(title or "추가 섹션", code or "", after=after, section_id=section_id)
            elif action == "replace":
                if not section_id:
                    return ToolResult("replace에는 section_id 필요", True)
                sec = doc.replace(section_id, code or "", title)
            elif action == "delete":
                if not section_id:
                    return ToolResult("delete에는 section_id 필요", True)
                sec = doc.delete(section_id)
            else:
                return ToolResult(f"알 수 없는 action: {action}", True)
        except (DoFileError, ServiceError) as e:
            return ToolResult(str(e), True)
        bak = backup_file(path, root)
        path.write_text(doc.render(), encoding="utf-8")
        guard = self._guard(sec.code()) if action != "delete" else GuardResult()
        shown = self.editor.show(path, self.session_id or "")
        self._record("stata_patch_dofile", file=filename, section=sec.id, action=action, status="ok",
                     backup=str(bak) if bak else None)
        lines = [f"✅ {filename} {sec.id} {({'add': '추가', 'replace': '교체', 'delete': '삭제'})[action]}"
                 f" (백업: {bak.name if bak else '없음'})"]
        if action == "delete":
            lines.append("참고: 원칙상 원 결과 섹션은 삭제보다 수정 섹션 추가가 권장됨")
        if guard.findings:
            lines.append("실행 전 참고 — " + guard.summary())
        lines.append(f"편집기: {shown.message}")
        return ToolResult("\n".join(lines))

    def show_in_editor(self, filename: str) -> ToolResult:
        try:
            path = self._project_file(filename)
        except ServiceError as e:
            return ToolResult(str(e), True)
        if not path.is_file():
            return ToolResult(f"파일 없음: {filename}", True)
        out = self.editor.show(path, self.session_id or "")
        return ToolResult(out.message, not out.ok)

    def run_section(self, filename: str, section_id: str, acknowledge_risks: bool = False) -> ToolResult:
        try:
            path = self._project_file(filename)
            doc = DoFile.parse(path.read_text(encoding="utf-8"))
            code = section_run_code(doc, section_id, self._version_line())
            sid = doc.get(section_id).id
        except (DoFileError, ServiceError, OSError) as e:
            return ToolResult(str(e), True)
        root = self._require_project()
        return self._guarded_run(
            "stata_run_section", code,
            lambda: self.backend.run_code(code, self.session_id or "", root),
            acknowledge_risks, file=filename, section=sid)

    def run_dofile(self, filename: str, acknowledge_risks: bool = False) -> ToolResult:
        try:
            path = self._project_file(filename)
            content = path.read_text(encoding="utf-8")
        except (ServiceError, OSError) as e:
            return ToolResult(str(e), True)
        root = self._require_project()
        return self._guarded_run(
            "stata_run_dofile", content,
            lambda: self.backend.run_dofile(path, self.session_id or "", root),
            acknowledge_risks, file=filename)

    def read_log(self, name: str | None = None, tail_lines: int | None = None, fmt: str = "text") -> ToolResult:
        root = self._require_project()
        if name:
            if "/" in name or "\\" in name or not name.lower().endswith(".log"):
                return ToolResult("output/logs 안의 .log 파일명만 허용", True)
            path = root / "output" / "logs" / name
        else:
            path = self.last_log_path
        if path is None or not path.is_file():
            return ToolResult("읽을 로그 없음", True)
        raw = path.read_text(encoding="utf-8", errors="replace")
        res = filter_output(raw, self.filter_cfg, str(path))
        text = res.text
        if tail_lines:
            text = "\n".join(text.splitlines()[-int(tail_lines):])
        if fmt == "dict":
            pairs, cur = [], None
            for line in text.splitlines():
                if line.startswith(". "):
                    cur = {"command": line[2:].strip(), "result": []}
                    pairs.append(cur)
                elif cur is not None:
                    cur["result"].append(line)
            for p in pairs:
                p["result"] = "\n".join(p["result"]).strip()
                m = re.search(r"^r\((\d+)\);", p["result"], re.MULTILINE)
                p["return_code"] = int(m.group(1)) if m else 0
            text = json.dumps(pairs, ensure_ascii=False, indent=2)
        note = f"\n[출력 필터 차단 {len(res.events)}건]" if res.events else ""
        return ToolResult(f"=== {path.name} (필터 적용) ===\n{text}{note}")

    def get_results(self, names: list[str] | None = None, kind: str | None = None) -> ToolResult:
        self._require_project()
        if not self.backend.persistent_session:
            return ToolResult("배치 모드에서는 저장결과가 유지되지 않음 → 로그에서 인용", True)
        if names:
            bad = [n for n in names if not _RESULT_NAME_RE.match(n)]
            if bad:
                return ToolResult(f"형식 오류: {', '.join(bad)} (예: e(r2), r(mean), _b[weight], 스칼라명)", True)
            outcome = self._run_internal(results_code(names))
            values: dict[str, object] = {}
            for fields in extract_markers(outcome.log_text, "SARES"):
                if len(fields) >= 2:
                    key, val = fields[0], fields[1]
                    try:
                        values[key] = float(val) if val not in ("", ".") else None
                    except ValueError:
                        values[key] = val
            missing = [n for n in names if n not in values]
            self._record("stata_get_results", status="ok")
            return ToolResult(json.dumps({"values": values, "not_found": missing}, ensure_ascii=False, indent=2))
        if kind in ("r", "e"):
            outcome = self._run_internal("return list" if kind == "r" else "ereturn list")
            text, _ = self._filtered(outcome)
            self._record("stata_get_results", status="ok" if outcome.ok else "error")
            return ToolResult(text, not outcome.ok)
        return ToolResult("names 또는 kind(r|e) 중 하나 필요", True)

    def export(self, mode: str, estimates: list[str] | None = None, filename: str | None = None,
               code: str | None = None, acknowledge_risks: bool = False) -> ToolResult:
        root = self._require_project()
        (root / "output" / "tables").mkdir(parents=True, exist_ok=True)
        if mode == "etable":
            if not estimates or not all(re.fullmatch(r"[A-Za-z_]\w{0,31}", e) for e in estimates):
                return ToolResult("estimates: estimates store로 저장한 이름 목록 필요", True)
            if not filename or not re.fullmatch(r"[A-Za-z0-9_\-]+\.(docx|xlsx|html|tex|md|txt|pdf)", filename):
                return ToolResult("filename 형식 오류(예: table1.docx)", True)
            target = f"output/tables/{filename}"
            run_code = f'etable, estimates({" ".join(estimates)}) mstat(N) export("{target}", replace)\n'
        elif mode == "custom":
            if not code:
                return ToolResult("mode=custom에는 code 필요", True)
            run_code, target = code, None
        else:
            return ToolResult("mode는 etable 또는 custom", True)
        result = self._guarded_run(
            "stata_export", run_code,
            lambda: self.backend.run_code(run_code, self.session_id or "", root),
            acknowledge_risks, export_file=target, estimates=estimates)
        if target and not result.is_error:
            exists = (root / target).is_file()
            result.text = (f"{'✅ 파일 생성' if exists else '⚠️ 파일 미확인'}: {target}\n") + result.text
        return result

    def reproduce(self, master: str | None = None) -> ToolResult:
        root = self._require_project()
        master = master or MASTER_NAME
        try:
            mpath = self._project_file(master)
        except ServiceError as e:
            return ToolResult(str(e), True)
        if not mpath.is_file():
            return ToolResult(f"{master} 없음", True)
        ok, why = self.batch.available()
        if not ok:
            return ToolResult(f"배치 실행 불가: {why}", True)
        guard = self._guard(mpath.read_text(encoding="utf-8"))
        if guard.blocked:
            return ToolResult("재현 실행 중단 — 하위 do-file에 차단 명령 포함\n" + guard.summary(), True)
        logs_dir = root / "output" / "logs"
        snap = root / ".stata-agent" / "reproduce" / datetime.now().strftime("%Y%m%d_%H%M%S") / "interactive"
        snap.mkdir(parents=True, exist_ok=True)
        before = {}
        for p in sorted(logs_dir.glob("*.log")):
            shutil.copy2(p, snap / p.name)
            before[p.name] = p.read_text(encoding="utf-8", errors="replace")
        outcome = self.batch.run_dofile(mpath, "reproduce", root)
        lines = [f"배치 재실행: {'성공' if outcome.ok else '오류'} (return code {outcome.return_code})"]
        if outcome.message:
            lines.append(outcome.message)
        mismatches = 0
        details = []
        compared = 0
        for name, old in before.items():
            new_path = logs_dir / name
            if not new_path.is_file():
                details.append(f"- {name}: 배치 실행 후 로그 없음")
                mismatches += 1
                continue
            res = compare_logs(old, new_path.read_text(encoding="utf-8", errors="replace"))
            compared += 1
            if res.equal:
                details.append(f"- {name}: 일치(수치 포함 {res.compared_lines}줄)")
            else:
                mismatches += 1
                first = res.diffs[0]
                details.append(f"- {name}: {res.verdict} — 예: 대화형 {first.line_a}행 {first.a[:6]} vs 배치 {first.line_b}행 {first.b[:6]} {res.note}")
        if not before:
            details.append("- 비교 대상 없음: output/logs에 대화형 전체 실행 로그가 없음(섹션 실행만 한 경우)")
        verdict = "재현 일치" if outcome.ok and mismatches == 0 and compared else f"불일치 {mismatches}건" if compared else "비교 불가"
        self._record("stata_reproduce", status="ok" if outcome.ok else "error", return_code=outcome.return_code,
                     reproduce={"verdict": verdict, "compared": compared, "mismatches": mismatches})
        lines.insert(0, f"재현 확인 결과: {verdict}")
        lines += details
        lines.append(f"대화형 로그 사본: {snap.relative_to(root)}")
        if not outcome.ok and outcome.log_text:
            text, _ = self._filtered(outcome)
            lines.append("\n=== 배치 로그 끝부분(필터 적용) ===\n" + "\n".join(text.splitlines()[-40:]))
        return ToolResult("\n".join(lines), not outcome.ok)

    def break_execution(self) -> ToolResult:
        out = self.backend.break_execution(self.session_id or "")
        return ToolResult(out.message, not out.ok)

    def install_package(self, package: str, source: str = "ssc", from_url: str | None = None) -> ToolResult:
        root = self._require_project()
        if not re.fullmatch(r"[A-Za-z0-9_]+", package or ""):
            return ToolResult("패키지명 형식 오류", True)
        if source == "net":
            if not from_url or not re.fullmatch(r"https?://[^\s\"']+", from_url):
                return ToolResult("net 설치에는 from_url(http/https) 필요", True)
            code = f'net install {package}, from("{from_url}") replace'
        else:
            code = f"ssc install {package}, replace"
        outcome = self.backend.run_code(code, self.session_id or "", root)
        text, _ = self._filtered(outcome)
        self._record("stata_install_package", package=package, status="ok" if outcome.ok else "error",
                     return_code=outcome.return_code)
        return ToolResult(("✅ 설치 완료\n" if outcome.ok else "❌ 설치 실패\n") + text, not outcome.ok)

    def usage_summary(self, client_name: str | None = None) -> ToolResult:
        self._require_project()
        summary = self.log.summary() if self.log else {}
        return ToolResult(json.dumps(summary, ensure_ascii=False, indent=2) + "\n\n" + disclosure_draft(summary, client_name))

    def child_for_selftest(self) -> "StataAgentService":
        """자가 점검용 별도 상태(세션·프로젝트)를 가진 복제본. 백엔드는 공유."""
        child = StataAgentService(self.settings, self.backend, self.batch, self._discovery)
        child.backend_reason = self.backend_reason
        child.version_line = self.version_line
        return child


def parse_schema(log_text: str) -> dict | None:
    head = {k: v for k, v, *_ in (f + [""] for f in extract_markers(log_text, "SASCHEMA")) if k}
    if "N" not in head:
        return None
    variables = []
    for fields in extract_markers(log_text, "SAVAR"):
        if len(fields) < 4:
            continue
        name, vtype, vlab, miss = fields[:4]
        label = "|".join(fields[4:]) if len(fields) > 4 else ""
        n = int(float(head.get("N") or 0))
        try:
            m = int(float(miss))
        except ValueError:
            m = None
        variables.append({
            "name": name, "type": vtype, "label": label, "value_label": vlab or None,
            "missing": m, "missing_pct": round(100 * m / n, 2) if (m is not None and n) else None,
        })
    return {"N": int(float(head["N"])), "K": int(float(head.get("K") or len(variables))), "variables": variables}


__all__ = ["StataAgentService", "ToolResult", "ServiceError", "parse_schema", "run_about"]
