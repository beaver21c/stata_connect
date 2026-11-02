"""Desktop Commander 차단 목록 보강(IMPLEMENTATION_STATUS §17) — Claude 앱에서 PC 명령 실행 도구로 Stata·SPSS를
직접 실행하지 못하게 함.

배경(2026-11-02 실기): Claude 앱에 Desktop Commander가 켜져 있으면 Claude가 Stata를 배치 실행하고 로그를 직접 읽음
→ 원자료 보호 검사(guard)·출력 필터를 거치지 않음. 사용자 결정: 안내 + 차단 설정 자동 추가.

Desktop Commander 동작 [1차 확인: wonderwhy-er/DesktopCommanderMCP main 소스 src/config.ts·command-manager.ts,
이 환경의 0.3.1 get_config]
- 설정 파일 ``~/.claude-server-commander/config.json``, 키 ``blockedCommands``(문자열 배열)
- 명령 문자열을 구분자(;·&&·||·| 등) 단위로 나눠 각 첫 낱말의 파일 이름(path.basename)을 소문자로 바꾼 뒤
  목록과 정확히 같을 때만 차단 → 목록에는 소문자 실행파일 이름(.exe 있음·없음 둘 다)을 넣음
- 설정 쓰기는 파일 잠금(proper-lockfile, ``config.json.lock``) 아래에서 다시 읽고 고쳐 씀

한계 [1차 확인: 같은 README "not a sandbox", "command blocking can be bypassed"]
- ``Start-Process``·스크립트·따옴표 안 공백 경로 등으로 우회 가능 → 사고 방지 장치일 뿐
- 파일 읽기 도구는 막지 못함(허용 폴더 목록만 있고 제외 목록 없음) → 분석 대화에서는 Desktop Commander를 끄도록 안내
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from .client_config import Change, backup

# 실행파일 이름(소문자). Windows 이름은 .exe 있음·없음 둘 다(PowerShell은 확장자 없이도 실행)
_STATA_BASE = ("statamp-64", "statase-64", "statabe-64", "stataic-64", "stata-64",
               "statamp", "statase", "statabe", "stataic", "stata")
STATA_COMMANDS = tuple(sorted({*_STATA_BASE, *(f"{n}.exe" for n in _STATA_BASE),
                               "stata-mp", "stata-se", "stata-be", "xstata", "xstata-mp", "xstata-se"}))
_SPSS_BASE = ("stats", "statisticsb", "runsyntx")
SPSS_COMMANDS = tuple(sorted({*_SPSS_BASE, *(f"{n}.exe" for n in _SPSS_BASE)}))


def dc_config_path() -> Path:
    return Path.home() / ".claude-server-commander" / "config.json"


def _locked(path: Path, fresh_seconds: float = 30.0) -> bool:
    lock = path.with_name(path.name + ".lock")
    try:
        return lock.exists() and (time.time() - lock.stat().st_mtime) < fresh_seconds
    except OSError:
        return False


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def add_blocked_commands(commands: tuple[str, ...], dry_run: bool = False, path: Path | None = None,
                         wait_seconds: float = 5.0) -> Change:
    """Desktop Commander 설정이 있을 때만 차단 목록에 추가(기존 항목 유지, 백업 후 원자적 쓰기)."""
    path = path or dc_config_path()
    label = "Desktop Commander 차단 목록"
    if not path.is_file():
        return Change(label, "skipped", "Desktop Commander 설정 없음(사용하지 않음)")
    deadline = time.monotonic() + wait_seconds
    while _locked(path) and time.monotonic() < deadline:
        time.sleep(0.5)
    if _locked(path):
        return Change(label, "error", "Desktop Commander가 설정을 쓰는 중 → Claude 앱을 종료하고 다시 실행")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (OSError, json.JSONDecodeError) as e:
        return Change(label, "error", f"설정 해석 실패 → 손대지 않음: {e}")
    if not isinstance(data, dict):
        return Change(label, "error", "설정 형식이 예상과 다름 → 손대지 않음")
    current = data.get("blockedCommands")
    if current is None:
        current = []
    if not isinstance(current, list):
        return Change(label, "error", "blockedCommands 형식이 예상과 다름 → 손대지 않음")
    have = {str(c).lower() for c in current}
    missing = [c for c in commands if c not in have]
    if not missing:
        return Change(label, "unchanged", "이미 추가됨")
    if dry_run:
        return Change(label, "planned", f"{len(missing)}개 추가 예정")
    data["blockedCommands"] = [*current, *missing]
    bak = backup(path)
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
    return Change(label, "updated", f"{len(missing)}개 추가(실행파일 이름 기준)", bak)


DC_NOTICE = ("Desktop Commander는 파일 읽기를 막을 수 없음 → Stata·SPSS 분석 대화에서는 "
             "Claude 앱에서 Desktop Commander를 끈 상태로 사용할 것")

__all__ = ["DC_NOTICE", "SPSS_COMMANDS", "STATA_COMMANDS", "add_blocked_commands", "dc_config_path"]
