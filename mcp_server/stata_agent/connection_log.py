"""AI 앱 연결 진단(IMPLEMENTATION_STATUS §19) — 연구자가 PC를 따로 조작하지 않아도 설치 도우미가
"Claude 앱이 이 도구를 시작했는지, 실패했다면 왜인지"를 보여 주기 위한 기록·판독.

배경(2026-11-02 실기): 설치 도우미는 "Claude 앱 등록 완료"였는데 새 채팅에 Stata 도구가 없음 →
(1) 앱이 그 설정 위치를 읽지 않음 (2) 읽었지만 실행파일 시작 실패 — 두 경우를 가를 근거가 화면에 없었음.

두 가지 기록
1. 도구 쪽 시작 기록: MCP 서버가 시작·도구 목록 요청을 받을 때마다 설치 폴더의 ``serve_history.jsonl``에
   시각·클라이언트 이름(MCP initialize의 clientInfo)만 남김(자료·코드·경로 원문 없음, 최근 50줄 유지)
2. Claude 앱 쪽 기록: 앱 설정 폴더의 ``logs\\mcp-server-<이름>.log``·``logs\\mcp.log``
   [2차 확인: MCP 공식 디버깅 안내의 로그 이름 규칙(이 작업 환경에서 원문 재열람 불가). 스토어판 위치는 설정 파일과 같은
   가상화 폴더로 추정 — 논리적 추론]
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

SERVE_LOG = "serve_history.jsonl"
_KEEP = 50


def record(install_dir: Path, event: str, **fields) -> None:
    """서버 시작·연결 기록. 어떤 경우에도 예외를 내지 않음(서버 동작을 막지 않게)."""
    try:
        install_dir.mkdir(parents=True, exist_ok=True)
        path = install_dir / SERVE_LOG
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, "pid": os.getpid()}
        entry.update({k: v for k, v in fields.items() if v is not None})
        lines = path.read_text(encoding="utf-8").splitlines()[-(_KEEP - 1):] if path.is_file() else []
        lines.append(json.dumps(entry, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 — 기록 실패는 무시
        pass


def read_records(install_dir: Path) -> list[dict]:
    path = install_dir / SERVE_LOG
    out = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _tail(path: Path, max_bytes: int = 200_000) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


_ERROR_WORDS = ("error", "failed", "exception", "enoent", "eacces", "spawn", "exited", "disconnected")


def claude_log_lines(server_name: str, config_path: Path, limit: int = 3) -> tuple[Path, float | None, bool, list[str]]:
    """(서버 전용 기록 파일, 그 파일의 마지막 수정 시각, 앱 기록에 이 서버 흔적이 있는지, 최근 오류 줄)."""
    logs = config_path.parent / "logs"
    own = logs / f"mcp-server-{server_name}.log"
    mtime = None
    if own.is_file():
        try:
            mtime = own.stat().st_mtime
        except OSError:
            pass
    seen = own.is_file()
    hits: list[str] = []
    for f in (own, logs / "mcp.log"):
        if not f.is_file():
            continue
        for line in _tail(f):
            low = line.lower()
            mine = f == own or server_name.lower() in low
            seen = seen or mine
            if mine and any(w in low for w in _ERROR_WORDS):
                hits.append(line.strip()[:220])
    return own, mtime, seen, hits[-limit:]


def connection_report(server_name: str, product: str, install_dir: Path, config_paths: list[Path]) -> list[str]:
    """설치 도우미·doctor 화면용 문장(쉬운 말)."""
    lines: list[str] = []
    recs = [r for r in read_records(install_dir) if r.get("event") == "list_tools"]
    if recs:
        last = recs[-1]
        who = last.get("client") or "앱 이름 미상"
        lines.append(f"{product} 도구가 AI 앱에 연결된 마지막 기록: {last.get('ts')} ({who})")
    else:
        lines.append(f"{product} 도구가 AI 앱에 연결된 기록 없음(이 버전 설치 뒤 아직 연결되지 않았거나, 앱이 시작하지 못함)")
    for cfg in config_paths:
        own, mtime, seen, hits = claude_log_lines(server_name, cfg)
        if not seen:
            lines.append(f"Claude 앱 기록에 '{server_name}' 시작 흔적 없음 → 앱이 이 위치({cfg.parent})의 설정을 아직 읽지 않았을 수 있음")
            continue
        when = datetime.fromtimestamp(mtime).isoformat(timespec="seconds") if mtime else "시각 미상"
        lines.append(f"Claude 앱이 '{server_name}'를 시작한 기록 있음(마지막 {when}, {own})")
        for h in hits:
            lines.append(f"  최근 오류: {h}")
    return lines


__all__ = ["SERVE_LOG", "claude_log_lines", "connection_report", "read_records", "record"]
