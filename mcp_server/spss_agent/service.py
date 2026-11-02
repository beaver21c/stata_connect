"""SPSS 도구 동작 — 흐름: guard → 고유값 점검 → 실행(엔진) → 출력 필터 → 사용 기록."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from stata_agent.config import Settings
from stata_agent.guard.command_policy import ACTION_LABEL, Action, GuardResult, default_file_reader
from stata_agent.guard.output_filter import FilterConfig
from stata_agent.log_compare import compare_logs
from stata_agent.service import ServiceError, ToolResult
from stata_agent.session_log import SessionLog, disclosure_draft

from . import __version__
from .backend import SpssBackend
from stata_agent.sync import FileWatch

from .importer import build_imported_syntax, outside_paths
from .resources import SPSS
from .backend import read_output as read_output_file
from .discovery import SpssInstall, discover
from .guard.output_filter import filter_output
from .guard.policy import SpssGuard, SpssGuardContext
from .project import init_project
from .readability import decorate_code, is_report, readability_notes, section_kind, section_title
from .syntaxfile import (
    ENCODING,
    MASTER_NAME,
    SyntaxFile,
    SyntaxFileError,
    backup_file,
    ensure_master_first,
    ensure_master_includes,
    master_entries,
    new_syntax,
    result_relpath,
    validate_filename,
)

AGENT_DIR = ".spss-agent"
# OMS FORMAT: DOC·XLS·PDF는 17부터, XLSX는 21부터(IBM OMS 문서 검색 요약 [2차 확인]).
# FORMAT=DOC는 28.0.1 전까지 Word 97-2003(.doc) 형식으로 저장 [2차 확인] → 27 이하에서 .docx 요청은 .doc로 저장.
_EXPORT_FORMATS = {".docx": "DOC", ".doc": "DOC", ".xlsx": "XLSX", ".xls": "XLS", ".html": "HTML", ".pdf": "PDF"}
DOCX_FROM_VERSION = 28


class SpssAgentService:
    def __init__(self, settings: Settings | None = None, backend: SpssBackend | None = None,
                 install: SpssInstall | None = None):
        self.settings = settings or Settings.from_env()
        if backend is None:
            self.installs, chosen = discover()
            backend = SpssBackend(install or chosen, float(os.environ.get("SPSS_AGENT_TIMEOUT", "900")))
        else:
            self.installs = [backend.install] if backend.install else []
        self.backend = backend
        self.filter_cfg = FilterConfig(max_chars=self.settings.max_output_chars)
        self.project_root: Path | None = None
        self.log: SessionLog | None = None
        self.files = FileWatch(SyntaxFile.parse)  # 연구자가 .sps를 직접 고친 경우 알림
        self.last_out: Path | None = None

    # ── 공통 ──
    def _require_project(self) -> Path:
        if self.project_root is None:
            raise ServiceError("프로젝트 세션 없음 → spss_open_session(project_dir)을 먼저 호출")
        return self.project_root

    def _project_file(self, filename: str) -> Path:
        root = self._require_project()
        name = str(filename or "").strip()
        if not name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ServiceError(f"프로젝트 폴더 기준 상대 파일명만 허용: {filename}")
        path = (root / name).resolve()
        if root.resolve() not in path.parents:
            raise ServiceError(f"프로젝트 폴더 밖 경로 거부: {filename}")
        return path

    def _guard(self, code: str) -> GuardResult:
        root = self._require_project()
        return SpssGuard(SpssGuardContext(str(root), read_file=_sps_reader)).check_code(code)

    def _record(self, tool: str, **fields) -> None:
        if self.log is not None:
            self.log.record(tool, backend=self.backend.name, **fields)

    def _identifier_check(self, guard: GuardResult) -> list[dict]:
        if not guard.identifier_vars:
            return []
        try:
            r = self.backend.unique(guard.identifier_vars)
        except Exception:
            return []
        flagged = []
        for name, c in (r.get("counts") or {}).items():
            n = c.get("nonmissing") or 0
            ratio = (c.get("unique", 0) / n) if n else 0.0
            if n and ratio > self.settings.unique_ratio:
                flagged.append({"variable": name, "ratio": round(ratio, 3)})
        return flagged

    def _guarded_run(self, tool: str, code: str, outfile: Path, acknowledge: bool,
                     run_code: str | None = None, **record) -> ToolResult:
        """guard는 code(사용자 문법)에, 실행은 run_code(없으면 code)에 적용."""
        guard = self._guard(code)
        rules = sorted({f.rule for f in guard.findings}) or None
        if guard.blocked:
            self._record(tool, status="blocked", guard_action="차단", guard_rules=rules, **record)
            return ToolResult("실행하지 않음 — 원자료 보호 규칙에 따라 차단\n" + guard.summary()
                              + "\n→ 차단 명령을 요약통계 등으로 바꿀 것. 꼭 필요하면 연구자가 SPSS에서 직접 실행.", True)
        if guard.needs_approval and not acknowledge:
            self._record(tool, status="needs_approval", guard_action="승인 필요", guard_rules=rules, **record)
            return ToolResult("실행 보류 — 연구자 확인 필요\n" + guard.summary()
                              + "\n→ 연구자에게 사유를 설명하고 동의를 받은 경우에만 acknowledge_risks=true로 다시 요청.", True)
        flagged = [] if acknowledge else self._identifier_check(guard)
        if flagged:
            self._record(tool, status="needs_approval", guard_action="승인 필요", guard_rules=["S14"], **record)
            desc = ", ".join(f"{f['variable']}(고유값 {f['ratio']:.0%})" for f in flagged)
            return ToolResult(f"실행 보류 — 식별자 성격 변수의 빈도·집단별 출력: {desc}\n"
                              "→ 개별 값이 노출될 수 있음. 범주화하거나, 연구자 동의 시 acknowledge_risks=true.", True)
        outcome = self.backend.run(run_code or code, outfile)
        root = self._require_project()
        last = root / AGENT_DIR / "last_run.txt"
        last.parent.mkdir(parents=True, exist_ok=True)
        last.write_text(outcome.log_text, encoding="utf-8")
        self.last_out = last
        res = filter_output(outcome.log_text, self.filter_cfg, str(outfile))
        self._record(tool, status="ok" if outcome.ok else "error", return_code=outcome.return_code,
                     guard_action=ACTION_LABEL[guard.action], guard_rules=rules,
                     blocked_output=[e.reason for e in res.events] or None,
                     acknowledged_risks=acknowledge or None, **record)
        head = [f"{'✅ 실행 완료' if outcome.ok else '❌ 실행 오류'} (SPSS 오류 수준 {outcome.return_code})"]
        if outcome.message:
            head.append(outcome.message)
        if any(f.action >= Action.WARN for f in guard.findings):
            head.append(guard.summary())
        if res.events:
            head.append(f"출력 필터 차단 {len(res.events)}건: " + "; ".join(e.reason for e in res.events))
        return ToolResult("\n".join(head) + "\n\n=== SPSS 출력(필터 적용) ===\n" + (res.text or "(출력 없음)"),
                          not outcome.ok)

    # ══ 도구 ══════════════════════════════════════════════════════
    def status(self, refresh: bool = False) -> ToolResult:
        if refresh and self.backend.engine is None:
            self.installs, chosen = discover()
            self.backend.install = chosen
        data = {
            "server_version": __version__,
            "backend": self.backend.status(),
            "installs": [i.public_dict() for i in self.installs if i],
            "project": str(self.project_root) if self.project_root else None,
            "note": "화면 없는 SPSS 엔진 사용 → 결과는 출력 파일로 확인. 저장결과(r()/e()) 개념 없음, 수치는 출력에서 인용",
        }
        return ToolResult(json.dumps(data, ensure_ascii=False, indent=2))

    def open_session(self, project_dir: str) -> ToolResult:
        root = Path(project_dir).expanduser()
        if not root.is_dir():
            return ToolResult(f"프로젝트 폴더 없음: {project_dir} (폴더를 먼저 만들 것)", True)
        root = root.resolve()
        created = init_project(root, hook=SPSS.hook_command())
        outcome = self.backend.open_session(root)
        if not outcome.ok:
            return ToolResult("세션 열기 실패: " + (outcome.message or "원인 미상"), True)
        self.project_root = root
        self.log = SessionLog(root, AGENT_DIR)
        self._record("spss_open_session", status="ok")
        lines = [f"✅ SPSS 세션 준비(화면 없음): {root}"]
        if self.backend.install and self.backend.install.version:
            lines.append(f"SPSS 버전(설치 폴더 기준): {self.backend.install.version}")
        if created:
            lines.append("생성한 규약 파일·폴더: " + ", ".join(created))
        return ToolResult("\n".join(lines))

    def load_data(self, path: str) -> ToolResult:
        root = self._require_project()
        p = Path(path)
        p = p if p.is_absolute() else root / p
        if not p.is_file() or p.suffix.lower() != ".sav":
            return ToolResult(f".sav 파일 없음: {path} (다른 형식은 GET DATA 명령을 섹션에 작성)", True)
        outcome = self.backend.run(f"GET FILE='{str(p).replace(chr(92), '/')}'.\nDATASET NAME main.",
                                   root / AGENT_DIR / "load.txt")
        if not outcome.ok:
            self._record("spss_load_data", status="error")
            return ToolResult("자료 불러오기 실패: " + (outcome.message or "출력 확인"), True)
        try:
            d = self.backend.dictionary(missing=False)
        except Exception as e:
            return ToolResult(f"변수 정보 조회 실패: {e}", True)
        self._record("spss_load_data", status="ok")
        return ToolResult(f"✅ 자료 불러옴: 사례 {d.get('cases')}개, 변수 {len(d.get('variables') or [])}개 "
                          "(값은 반환하지 않음 → 구조는 spss_schema)")

    def schema(self) -> ToolResult:
        self._require_project()
        try:
            d = self.backend.dictionary(missing=True)
        except Exception as e:
            return ToolResult(f"스키마 조회 실패(자료가 열려 있는지 확인): {e}", True)
        if not d.get("ok", True):
            return ToolResult(f"스키마 조회 실패: {d.get('error')}", True)
        cases = d.get("cases") or 0
        for v in d.get("variables") or []:
            m = v.get("missing")
            v["missing_pct"] = round(100 * m / cases, 2) if (m is not None and cases) else None
        self._record("spss_schema", status="ok")
        return ToolResult(json.dumps({"cases": cases, "variables": d.get("variables")}, ensure_ascii=False, indent=2))

    def write_syntax(self, filename: str, sections: list[dict], author: str | None = None,
                     overwrite: bool = False) -> ToolResult:
        root = self._require_project()
        try:
            validate_filename(filename)
            path = self._project_file(filename)
            if path.exists() and not overwrite:
                return ToolResult(f"이미 있는 파일: {filename} → spss_patch_syntax 사용(또는 overwrite=true)", True)
            kinds = [s.get("kind") if s.get("kind") in ("analysis", "report") else "analysis" for s in sections or []]
            pairs = [(section_title(str(s.get("title", "")), k), decorate_code(str(s.get("code", "")), k))
                     for s, k in zip(sections or [], kinds)]
            if not pairs:
                return ToolResult("sections가 비어 있음", True)
            content = new_syntax(filename, pairs, author or "AI")
            read_notes = [f"S{i:02d} {t}: {n}" for i, ((t, c), k) in enumerate(zip(pairs, kinds), start=1)
                          for n in readability_notes(c, k)]
        except (SyntaxFileError, ServiceError) as e:
            return ToolResult(str(e), True)
        bak = backup_file(path, root, AGENT_DIR) if path.exists() else None
        path.write_text(content, encoding=ENCODING)
        self.files.remember(path, content)
        master = root / MASTER_NAME
        master.write_text(ensure_master_includes(
            master.read_text(encoding="utf-8-sig") if master.is_file() else None, filename), encoding=ENCODING)
        guard = self._guard(content)
        self._record("spss_write_syntax", file=filename, status="ok", backup=str(bak) if bak else None,
                     guard_action=ACTION_LABEL[guard.action])
        n_report = kinds.count("report")
        lines = [f"✅ 작성: {filename} (섹션 {len(pairs)}개 = 분석 {len(pairs) - n_report}·보고용 {n_report}, 00_master.sps 갱신)"]
        if read_notes:
            lines.append("가독성 참고(연구자가 분석을 확인하기 쉽게):")
            lines += [f"- {n}" for n in read_notes]
        if guard.findings:
            lines.append("실행 전 참고 — " + guard.summary())
        return ToolResult("\n".join(lines))

    def patch_syntax(self, filename: str, action: str, section_id: str | None = None, title: str | None = None,
                     code: str | None = None, after: str | None = None, kind: str | None = None) -> ToolResult:
        root = self._require_project()
        try:
            path = self._project_file(filename)
            if not path.is_file():
                return ToolResult(f"파일 없음: {filename} → spss_write_syntax로 먼저 작성", True)
            current = self._read_syntax(path)
            file_notes = self.files.changes(path, current)
            doc = SyntaxFile.parse(current)
            kind = kind if kind in ("analysis", "report") else None
            if action == "add":
                kind = kind or "analysis"
                sec = doc.add(section_title(title or "추가 섹션", kind), decorate_code(code or "", kind),
                              after=after, section_id=section_id)
            elif action in ("replace", "delete"):
                if not section_id:
                    return ToolResult(f"{action}에는 section_id 필요", True)
                if action == "replace":
                    old_title = doc.get(section_id).title
                    kind = kind or section_kind(old_title)
                    sec = doc.replace(section_id, decorate_code(code or "", kind), section_title(title or old_title, kind))
                else:
                    sec = doc.delete(section_id)
            else:
                return ToolResult(f"알 수 없는 action: {action}", True)
        except (SyntaxFileError, ServiceError) as e:
            return ToolResult(str(e), True)
        bak = backup_file(path, root, AGENT_DIR)
        rendered = doc.render()
        path.write_text(rendered, encoding=ENCODING)
        self.files.remember(path, rendered)
        guard = self._guard(sec.code()) if action != "delete" else GuardResult()
        self._record("spss_patch_syntax", file=filename, section=sec.id, action=action, status="ok",
                     backup=str(bak) if bak else None)
        lines = [f"✅ {filename} {sec.id} {({'add': '추가', 'replace': '교체', 'delete': '삭제'})[action]}"
                 f" (백업: {bak.name if bak else '없음'})"]
        lines += [f"⚠️ {n}" for n in file_notes]
        if action != "delete":
            notes = readability_notes(sec.code(), section_kind(sec.title))
            if notes:
                lines.append("가독성 참고(연구자가 분석을 확인하기 쉽게):")
                lines += [f"- {n}" for n in notes]
        if guard.findings:
            lines.append("실행 전 참고 — " + guard.summary())
        return ToolResult("\n".join(lines))

    def _read_syntax(self, path: Path) -> str:
        """UTF-8 문법 파일만 읽음. 그 밖(SPSS 코드페이지 모드의 cp949 등)은 가져오기 도구 안내."""
        from stata_agent.importer import decode_text, is_utf8

        data = path.read_bytes()
        if not is_utf8(data):
            _, enc = decode_text(data)
            raise ServiceError(f"UTF-8이 아닌 파일({enc} 추정): {path.name} → spss_import_syntax로 가져오기"
                               "(원본 백업 후 UTF-8 변환·섹션 표지 추가)를 먼저 실행")
        return data.decode("utf-8").lstrip("\ufeff")

    def import_syntax(self, filename: str, preview: bool = False) -> ToolResult:
        """연구자가 쓰던 .sps를 이어 작업용으로 준비(그 자리 수정 + 백업). 실행하지 않음."""
        from stata_agent.importer import decode_text

        root = self._require_project()
        try:
            path = self._project_file(filename)
        except ServiceError as e:
            return ToolResult(str(e), True)
        if path.suffix.lower() != ".sps" or not path.is_file():
            return ToolResult(f"문법 파일 없음: {filename} (프로젝트 폴더 안 .sps 파일)", True)
        if path.name == MASTER_NAME:
            return ToolResult(f"{MASTER_NAME}는 자동 관리 대상", True)
        data = path.read_bytes()
        text, enc = decode_text(data)
        text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        guard = self._guard(text)
        row_lines = [f.line for f in guard.findings if f.rule == "S01" and not f.source]
        new_text, meta, kind, commented, manual = build_imported_syntax(text, row_lines)
        handled = {ln for ln, _ in commented} | {ln for ln, _ in manual}
        others = [f.as_text() for f in guard.findings
                  if not (f.rule == "S01" and not f.source and f.line in handled)]
        converted = enc not in ("utf-8", "utf-8-sig")
        paths = outside_paths(text.split("\n"), root)
        lines = [f"{'미리보기(변경 없음)' if preview else '✅ 가져오기 완료'}: {filename}"]
        lines.append(f"- 인코딩: {enc}" + (" → UTF-8(BOM)로 변환" if converted else " (변환 없음)"))
        if not meta:
            lines.append("- 섹션 표지: 이미 있음(분할 생략)")
        else:
            how = {"decorated": "장식 주석 제목", "numbered": "번호 제목", None: "제목을 찾지 못해 통째로 1개"}[kind]
            lines.append(f"- 섹션 {len(meta)}개({how} 기준):")
            lines += [f"  {sid} {title} (원래 {ln}행부터)" for sid, title, ln in meta]
        if commented:
            lines.append("- 원자료 보호로 주석 처리한 명령(연구자가 SPSS에서 직접 실행):")
            lines += [f"  {ln}행: {code}" for ln, code in commented]
        if manual:
            lines.append("- 손으로 고쳐야 하는 명령(마침표 없이 끝나는 명령 등):")
            lines += [f"  {ln}행: {code}" for ln, code in manual]
        if others:
            lines.append("- 실행 전 확인 대상(파일은 그대로 둠): " + "; ".join(others[:15])
                         + (f" 외 {len(others) - 15}건" if len(others) > 15 else ""))
        if paths:
            lines.append("- 프로젝트 폴더 밖 경로(재현을 위해 자료를 data/로 옮기는 것을 권장):")
            lines += [f"  {ln}행: {code}" for ln, code in paths[:10]]
        if preview:
            return ToolResult("\n".join(lines))
        bak = backup_file(path, root, AGENT_DIR)
        path.write_text(new_text, encoding=ENCODING)
        self.files.remember(path, new_text)
        lines.append(f"- 원본 백업: {AGENT_DIR}/backups/{bak.name if bak else '없음'}")
        master = root / MASTER_NAME
        master.write_text(ensure_master_first(master.read_text(encoding="utf-8-sig") if master.is_file() else None,
                                              path.relative_to(root).as_posix()), encoding=ENCODING)
        lines.append(f"- {MASTER_NAME} 맨 앞에 등록")
        lines.append("다음: spss_run_syntax_file로 이 파일 전체를 한 번 실행해 자료 상태를 복원한 뒤 "
                     "spss_patch_syntax(action=add)로 새 섹션을 이어 붙임")
        self._record("spss_import_syntax", file=filename, status="ok", encoding=enc,
                     sections=len(meta), commented=len(commented), manual=len(manual))
        return ToolResult("\n".join(lines))

    def run_section(self, filename: str, section_id: str, acknowledge_risks: bool = False) -> ToolResult:
        try:
            path = self._project_file(filename)
            current = self._read_syntax(path)
            file_notes = self.files.changes(path, current)
            sec = SyntaxFile.parse(current).get(section_id)
        except (SyntaxFileError, ServiceError, OSError) as e:
            return ToolResult(str(e), True)
        root = self._require_project()
        result = self._guarded_run("spss_run_section", sec.code() + "\n", root / AGENT_DIR / "section.txt",
                                   acknowledge_risks, file=filename, section=sec.id)
        if file_notes:
            result.text = "".join(f"⚠️ {n}\n" for n in file_notes) + result.text
        if is_report(sec.title):
            result.text = ("※ 보고용 계산 섹션(연구자 확인 생략 가능) — 분석 결과의 근거는 분석 섹션의 SPSS 출력\n"
                           + result.text)
        return result

    def run_syntax_file(self, filename: str, acknowledge_risks: bool = False) -> ToolResult:
        try:
            path = self._project_file(filename)
            content = self._read_syntax(path)
        except (SyntaxFileError, ServiceError, OSError) as e:
            return ToolResult(str(e), True)
        root = self._require_project()
        return self._guarded_run("spss_run_syntax_file", content, root / result_relpath(path.name),
                                 acknowledge_risks, file=filename)

    def read_output(self, name: str | None = None, tail_lines: int | None = None) -> ToolResult:
        root = self._require_project()
        if name:
            if "/" in name or "\\" in name or not name.lower().endswith(".txt"):
                return ToolResult("output/logs 안의 .txt 파일명만 허용", True)
            path = root / "output" / "logs" / name
        else:
            path = self.last_out
        if path is None or not path.is_file():
            return ToolResult("읽을 출력 없음", True)
        res = filter_output(read_output_file(path), self.filter_cfg, str(path))
        text = "\n".join(res.text.splitlines()[-int(tail_lines):]) if tail_lines else res.text
        return ToolResult(f"=== {path.name} (필터 적용) ===\n{text}"
                          + (f"\n[출력 필터 차단 {len(res.events)}건]" if res.events else ""))

    def export(self, filename: str, section_id: str, output: str, acknowledge_risks: bool = False) -> ToolResult:
        root = self._require_project()
        ext = Path(output).suffix.lower()
        if ext not in _EXPORT_FORMATS or not re.fullmatch(r"[A-Za-z0-9_\-]+\.[a-z]+", output):
            return ToolResult("output 형식 오류(예: table1.docx / .doc / .xlsx / .xls / .html / .pdf)", True)
        try:
            sec = SyntaxFile.parse(self._project_file(filename).read_text(encoding="utf-8-sig")).get(section_id)
        except (SyntaxFileError, ServiceError, OSError) as e:
            return ToolResult(str(e), True)
        note = ""
        version = self.backend.install.version if self.backend.install else None
        if ext == ".docx" and version is not None and version < DOCX_FROM_VERSION:
            output = output[: -len(ext)] + ".doc"
            note = f"ℹ️ SPSS {version}의 Word 내보내기는 .doc(Word 97-2003) 형식 → {output}로 저장\n"
        elif ext == ".docx" and version == DOCX_FROM_VERSION:
            note = "ℹ️ SPSS 28.0.0은 .doc 형식으로 저장될 수 있음(28.0.1부터 .docx) — Word에서 열리지 않으면 .doc로 다시 요청\n"
        target = root / "output" / "tables" / output
        target.parent.mkdir(parents=True, exist_ok=True)
        code = (f"OMS /TAG='SAEXPORT' /SELECT TABLES /DESTINATION FORMAT={_EXPORT_FORMATS[ext]} "
                f"OUTFILE='{str(target).replace(chr(92), '/')}'.\n{sec.code()}\nOMSEND TAG='SAEXPORT'.\n")
        res = self._guarded_run("spss_export", sec.code(), root / AGENT_DIR / "export.txt", acknowledge_risks,
                                run_code=code, file=filename, section=sec.id, export_file=f"output/tables/{output}")
        if not res.is_error:
            res.text = note + (f"{'✅ 파일 생성' if target.is_file() else '⚠️ 파일 미확인'}: output/tables/{output}\n") + res.text
        return res

    def reproduce(self) -> ToolResult:
        root = self._require_project()
        master = root / MASTER_NAME
        if not master.is_file():
            return ToolResult("00_master.sps 없음", True)
        entries = master_entries(master.read_text(encoding="utf-8-sig"))
        if not entries:
            return ToolResult("00_master.sps에 INSERT 목록이 없음", True)
        for name in entries:
            g = self._guard((root / name).read_text(encoding="utf-8-sig") if (root / name).is_file() else "")
            if g.blocked:
                return ToolResult(f"재현 실행 중단 — {name}에 차단 명령 포함\n" + g.summary(), True)
        fresh = self.backend.fresh()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = root / AGENT_DIR / "reproduce" / stamp
        opened = fresh.open_session(root, engine_dir=f"{AGENT_DIR}/reproduce/{stamp}/engine")
        if not opened.ok:
            return ToolResult("재현용 SPSS 엔진 기동 실패: " + opened.message, True)
        lines, mismatches, compared = [], 0, 0
        try:
            for name in entries:
                src = root / name
                if not src.is_file():
                    lines.append(f"- {name}: 파일 없음")
                    mismatches += 1
                    continue
                batch_out = out_dir / f"{Path(name).stem}.txt"
                outcome = fresh.run(src.read_text(encoding="utf-8-sig"), batch_out)
                interactive = root / result_relpath(name)
                if not outcome.ok:
                    lines.append(f"- {name}: 재실행 오류({outcome.message})")
                    mismatches += 1
                    continue
                if not interactive.is_file():
                    lines.append(f"- {name}: 대화형 전체 실행 출력 없음(비교 생략)")
                    continue
                res = compare_logs(read_output_file(interactive), outcome.log_text)
                compared += 1
                if res.equal:
                    lines.append(f"- {name}: 일치(수치 포함 {res.compared_lines}줄)")
                else:
                    mismatches += 1
                    d = res.diffs[0]
                    lines.append(f"- {name}: {res.verdict} — 예: 대화형 {d.line_a}행 {d.a[:6]} vs 재실행 {d.line_b}행 {d.b[:6]} {res.note}")
        finally:
            fresh.close()
        verdict = ("재현 일치" if compared else "비교 불가") if mismatches == 0 else f"불일치 {mismatches}건"
        self._record("spss_reproduce", status="ok", reproduce={"verdict": verdict, "compared": compared,
                                                               "mismatches": mismatches})
        return ToolResult("\n".join([f"재현 확인 결과: {verdict}", *lines,
                                     f"재실행 출력: {out_dir.relative_to(root)}"]), mismatches > 0)

    def usage_summary(self, client_name: str | None = None) -> ToolResult:
        self._require_project()
        summary = self.log.summary() if self.log else {}
        return ToolResult(json.dumps(summary, ensure_ascii=False, indent=2) + "\n\n"
                          + disclosure_draft(summary, client_name, software="SPSS", script_name="문법 파일"))

    def child_for_selftest(self) -> "SpssAgentService":
        child = SpssAgentService(self.settings, self.backend.fresh())
        child.installs = self.installs
        return child


def _sps_reader(path: str) -> str | None:
    text = default_file_reader(path)
    return text.lstrip("﻿") if text is not None else None


__all__ = ["SpssAgentService", "AGENT_DIR"]
