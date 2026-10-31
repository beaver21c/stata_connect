"""Claude Code 실행 전 검사(PreToolUse hook) — 셸 명령이 원자료·Stata를 직접 다루지 못하게 막음.

배경(Claude Code 공식 문서 permissions·hooks, 2026-10 확인)
- 프로젝트 설정의 ``Read(/data/**)`` 거부 규칙은 Claude의 파일 도구와 Claude Code가 인식하는
  셸 파일 명령(cat·head 등)에는 적용되나, 스크립트가 파일을 스스로 여는 경우에는 적용되지 않음
- Windows 기본 실행 환경은 운영체제 수준 격리(sandbox)를 지원하지 않음
→ 이 검사는 명령 문자열을 보고 막는 보조 장치임. 문자열을 조립하는 스크립트 등으로 우회 가능(논리적 추론)

입력: stdin JSON(``tool_name``, ``tool_input.command``) / 차단: 종료 코드 2 + stderr 사유
"""

from __future__ import annotations

import json
import re
import sys

SHELL_TOOLS = ("Bash", "PowerShell")

# data/ 또는 data\ 로 시작하는 경로 조각(metadata/ 등 단어 일부는 제외)
_DATA_PATH = re.compile(r"(?<![\w.\-])data[\\/]", re.IGNORECASE)
# data 폴더로 이동
_DATA_CD = re.compile(
    r"(?:^|[\s;&|(])(?:cd|pushd|chdir|set-location|sl)\s+[\"']?(?:\.[\\/])?data[\"']?(?=$|[\s;&|)])",
    re.IGNORECASE,
)
# 통계 패키지 원자료 형식
_RAW_FILE = re.compile(r"\.(?:dta|sav|zsav|por|sas7bdat|xpt|rds|rdata|parquet|feather)\b", re.IGNORECASE)
# Stata 직접 실행(배치·COM) — MCP 도구의 guard·출력 필터를 거치지 않으므로 차단
_STATA_RUN = re.compile(
    r"stata(?:mp|se|be|ic)?(?:-64)?\.exe"
    r"|\bstata(?:mp|se|be|ic)?-64\b"
    r"|\bstata-(?:mp|se|be)\b"
    r"|\bxstata(?:-mp|-se)?\b"
    r"|stata\.stataoleapp"
    r"|(?:^|[;&|]\s*)stata\s",
    re.IGNORECASE,
)

REASON_DATA = "원자료 보호: data/ 폴더나 원자료 파일(.dta·.sav 등)을 셸 명령으로 다루지 않음 → stata 도구(stata_schema·stata_run_section 등) 사용"
REASON_STATA = "Stata 직접 실행 금지: 셸에서 Stata를 실행하면 원자료 보호 검사를 거치지 않음 → stata 도구(stata_run_section·stata_run_dofile) 사용"


def check_command(command: str) -> str | None:
    """차단 사유 또는 None."""
    if not command:
        return None
    if _STATA_RUN.search(command):
        return REASON_STATA
    if _DATA_PATH.search(command) or _DATA_CD.search(command) or _RAW_FILE.search(command):
        return REASON_DATA
    return None


def evaluate(payload: dict) -> str | None:
    if payload.get("tool_name") not in SHELL_TOOLS:
        return None
    tool_input = payload.get("tool_input") or {}
    return check_command(str(tool_input.get("command") or ""))


def main(stdin=None, stderr=None) -> int:
    stdin = stdin or sys.stdin
    stderr = stderr or sys.stderr
    try:
        payload = json.loads(stdin.read() or "{}")
    except (ValueError, UnicodeDecodeError):
        return 0  # 입력을 해석하지 못하면 통상 권한 확인 절차에 맡김
    reason = evaluate(payload if isinstance(payload, dict) else {})
    if reason:
        stderr.write(reason + "\n")
        return 2
    return 0
