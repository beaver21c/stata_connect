"""AI 사용 기록(설계서 P6) — ``.stata-agent/history.jsonl``.

기록 대상: 도구 이름·대상 파일·섹션·반환코드·guard 판정·차단 사유·재현 결과
기록 금지: 자료 값, 로그 원문, 변수값(→ 기록 파일 자체가 원자료를 담지 않도록)
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

_ALLOWED_KEYS = {
    "tool", "session_id", "file", "section", "status", "return_code", "guard_action",
    "guard_rules", "blocked_output", "acknowledged_risks", "backend", "message", "reproduce",
    "backup", "action", "package", "estimates", "export_file", "client",
}


RUN_TOOLS = {"stata_run_section", "stata_run_dofile", "spss_run_section", "spss_run_syntax_file"}
REPRODUCE_TOOLS = {"stata_reproduce", "spss_reproduce"}
WRITE_TOOLS = ("stata_write_dofile", "spss_write_syntax")
PATCH_TOOLS = ("stata_patch_dofile", "spss_patch_syntax")


class SessionLog:
    def __init__(self, project_root: Path, dirname: str = ".stata-agent"):
        self.path = Path(project_root) / dirname / "history.jsonl"

    def record(self, tool: str, **fields: Any) -> dict:
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "tool": tool}
        for k, v in fields.items():
            if k in _ALLOWED_KEYS and v is not None:
                entry[k] = v if not isinstance(v, Path) else str(v)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def summary(self) -> dict:
        entries = self.read()
        tools = Counter(e.get("tool") for e in entries)
        runs = [e for e in entries if e.get("tool") in RUN_TOOLS]
        blocked = [e for e in entries if e.get("guard_action") == "차단" or e.get("blocked_output")]
        reproduce = [e.get("reproduce") for e in entries if e.get("tool") in REPRODUCE_TOOLS and e.get("reproduce")]
        files = sorted({e["file"] for e in entries if e.get("file")})
        return {
            "period": [entries[0]["ts"], entries[-1]["ts"]] if entries else None,
            "tool_calls": dict(tools),
            "runs_total": len(runs),
            "runs_failed": sum(1 for e in runs if e.get("status") not in ("ok", None)),
            "dofiles_written": sum(tools.get(t, 0) for t in WRITE_TOOLS),
            "dofile_patches": sum(tools.get(t, 0) for t in PATCH_TOOLS),
            "guard_or_filter_blocks": len(blocked),
            "risk_acknowledged_runs": sum(1 for e in runs if e.get("acknowledged_risks")),
            "reproduce_results": reproduce,
            "files": files,
        }


def disclosure_draft(summary: dict, client: str | None = None, software: str = "Stata",
                     script_name: str = "do-file") -> str:
    """논문 Method 절 AI 사용 공개문 초안(연구자가 반드시 검토·수정)."""
    period = summary.get("period") or ["(기록 없음)", "(기록 없음)"]
    repro = summary.get("reproduce_results") or []
    last = repro[-1] if repro else None
    repro_txt = (
        f"최종 배치 재실행 결과 대화형 결과와 {last.get('verdict', '판정 미상')}"
        if isinstance(last, dict) else "배치 재실행 재현 확인 기록 없음"
    )
    return (
        "[AI 사용 공개문 초안 — 연구자 검토 필요]\n"
        f"본 연구의 자료 분석에는 생성형 AI({client or '사용 도구명 기입'})를 {software} 분석 보조 도구로 활용하였다. "
        f"AI는 {script_name} 작성·수정과 실행 결과 판독을 보조하였으며, 모든 통계량은 {software}가 산출하였다. "
        "개별 관측치 값은 AI에 전송하지 않도록 명령 차단·출력 필터를 적용하였다. "
        f"기록 기간 {period[0]}~{period[1]} 동안 {script_name} 신규 작성 {summary.get('dofiles_written', 0)}건, "
        f"섹션 수정 {summary.get('dofile_patches', 0)}건, {software} 실행 {summary.get('runs_total', 0)}회"
        f"(오류 {summary.get('runs_failed', 0)}회)가 있었다. {repro_txt}. "
        "연구자는 모든 실행 코드를 실행 전에 검토·승인하였고, 결과 해석의 최종 책임은 연구자에게 있다. "
        f"분석 {script_name}과 실행 결과는 재현 자료로 보존하였다."
    )
