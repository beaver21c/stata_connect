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
from .discovery import SpssInstall, discover
from .guard.output_filter import filter_output
from .guard.policy import SpssGuard, SpssGuardContext
from .project import init_project
from .syntaxfile import (
    ENCODING,
    MASTER_NAME,
    SyntaxFile,
    SyntaxFileError,
    backup_file,
    ensure_master_includes,
    master_entries,
    new_syntax,
    result_relpath,
    validate_filename,
)

AGENT_DIR = ".spss-agent"
_EXPORT_FORMATS = {".docx": "DOC", ".xlsx": "XLSX", ".html": "HTML", ".pdf": "PDF"}


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
        created = init_project(root)
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
            pairs = [(str(s.get("title", "")), str(s.get("code", ""))) for s in sections or []]
            if not pairs:
                return ToolResult("sections가 비어 있음", True)
            content = new_syntax(filename, pairs, author or "AI")
        except (SyntaxFileError, ServiceError) as e:
            return ToolResult(str(e), True)
        bak = backup_file(path, root) if path.exists() else None
        path.write_text(content, encoding=ENCODING)
        master = root / MASTER_NAME
        master.write_text(ensure_master_includes(
            master.read_text(encoding="utf-8-sig") if master.is_file() else None, filename), encoding=ENCODING)
        guard = self._guard(content)
        self._record("spss_write_syntax", file=filename, status="ok", backup=str(bak) if bak else None,
                     guard_action=ACTION_LABEL[guard.action])
        lines = [f"✅ 작성: {filename} (섹션 {len(pairs)}개, 00_master.sps 갱신)"]
        if guard.findings:
            lines.append("실행 전 참고 — " + guard.summary())
        return ToolResult("\n".join(lines))

    def patch_syntax(self, filename: str, action: str, section_id: str | None = None, title: str | None = None,
                     code: str | None = None, after: str | None = None) -> ToolResult:
        root = self._require_project()
        try:
            path = self._project_file(filename)
            if not path.is_file():
                return ToolResult(f"파일 없음: {filename} → spss_write_syntax로 먼저 작성", True)
            doc = SyntaxFile.parse(path.read_text(encoding="utf-8-sig"))
            if action == "add":
                sec = doc.add(title or "추가 섹션", code or "", after=after, section_id=section_id)
            elif action in ("replace", "delete"):
                if not section_id:
                    return ToolResult(f"{action}에는 section_id 필요", True)
                sec = doc.replace(section_id, code or "", title) if action == "replace" else doc.delete(section_id)
            else:
                return ToolResult(f"알 수 없는 action: {action}", True)
        except (SyntaxFileError, ServiceError) as e:
            return ToolResult(str(e), True)
        bak = backup_file(path, root)
        path.write_text(doc.render(), encoding=ENCODING)
        guard = self._guard(sec.code()) if action != "delete" else GuardResult()
        self._record("spss_patch_syntax", file=filename, section=sec.id, action=action, status="ok",
                     backup=str(bak) if bak else None)
        lines = [f"✅ {filename} {sec.id} {({'add': '추가', 'replace': '교체', 'delete': '삭제'})[action]}"
                 f" (백업: {bak.name if bak else '없음'})"]
        if guard.findings:
            lines.append("실행 전 참고 — " + guard.summary())
        return ToolResult("\n".join(lines))

    def run_section(self, filename: str, section_id: str, acknowledge_risks: bool = False) -> ToolResult:
        try:
            path = self._project_file(filename)
            sec = SyntaxFile.parse(path.read_text(encoding="utf-8-sig")).get(section_id)
        except (SyntaxFileError, ServiceError, OSError) as e:
            return ToolResult(str(e), True)
        root = self._require_project()
        return self._guarded_run("spss_run_section", sec.code() + "\n", root / AGENT_DIR / "section.txt",
                                 acknowledge_risks, file=filename, section=sec.id)

    def run_syntax_file(self, filename: str, acknowledge_risks: bool = False) -> ToolResult:
        try:
            path = self._project_file(filename)
            content = path.read_text(encoding="utf-8-sig")
            validate_filename(path.name)
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
        res = filter_output(path.read_text(encoding="utf-8-sig", errors="replace"), self.filter_cfg, str(path))
        text = "\n".join(res.text.splitlines()[-int(tail_lines):]) if tail_lines else res.text
        return ToolResult(f"=== {path.name} (필터 적용) ===\n{text}"
                          + (f"\n[출력 필터 차단 {len(res.events)}건]" if res.events else ""))

    def export(self, filename: str, section_id: str, output: str, acknowledge_risks: bool = False) -> ToolResult:
        root = self._require_project()
        ext = Path(output).suffix.lower()
        if ext not in _EXPORT_FORMATS or not re.fullmatch(r"[A-Za-z0-9_\-]+\.[a-z]+", output):
            return ToolResult("output 형식 오류(예: table1.docx / .xlsx / .html / .pdf)", True)
        try:
            sec = SyntaxFile.parse(self._project_file(filename).read_text(encoding="utf-8-sig")).get(section_id)
        except (SyntaxFileError, ServiceError, OSError) as e:
            return ToolResult(str(e), True)
        target = root / "output" / "tables" / output
        target.parent.mkdir(parents=True, exist_ok=True)
        code = (f"OMS /TAG='SAEXPORT' /SELECT TABLES /DESTINATION FORMAT={_EXPORT_FORMATS[ext]} "
                f"OUTFILE='{str(target).replace(chr(92), '/')}'.\n{sec.code()}\nOMSEND TAG='SAEXPORT'.\n")
        res = self._guarded_run("spss_export", sec.code(), root / AGENT_DIR / "export.txt", acknowledge_risks,
                                run_code=code, file=filename, section=sec.id, export_file=f"output/tables/{output}")
        if not res.is_error:
            res.text = (f"{'✅ 파일 생성' if target.is_file() else '⚠️ 파일 미확인'}: output/tables/{output}\n") + res.text
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
                res = compare_logs(interactive.read_text(encoding="utf-8-sig", errors="replace"), outcome.log_text)
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
