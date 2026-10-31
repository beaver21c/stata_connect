"""환경변수 기반 설정. MCP 클라이언트 설정의 env 항목으로 전달.

| 변수 | 기본값 | 의미 |
|---|---|---|
| STATA_AGENT_STATA_EXE | (탐지) | 사용할 Stata 실행파일 고정 |
| STATA_AGENT_BACKEND | auto | auto / com / batch |
| STATA_AGENT_PROJECT | (없음) | 기본 프로젝트 폴더 |
| STATA_AGENT_MAX_OUTPUT_CHARS | 20000 | AI 반환 로그 최대 글자 수 |
| STATA_AGENT_MASK_SMALL_CELLS | 0 | 빈도표 소표본 셀 마스킹 기준(0=끔, 예: 5) |
| STATA_AGENT_UNIQUE_RATIO | 0.9 | 식별자 성격 판정 고유값 비율 |
| STATA_AGENT_BATCH_TIMEOUT | 3600 | 배치 실행 제한 시간(초) |
| STATA_AGENT_EDITOR | doedit | 편집기 연동 방식(doedit / none) |
| STATA_AGENT_REPORT_DIR | ~/Documents/StataAgent | 점검 보고서 저장 폴더 |
| STATA_AGENT_STATA_VERSION | (탐지) | do-file version 선언 고정(예: 18) |
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


_PLACEHOLDER = re.compile(r"^\$\{[^}]*\}$")


def _env(name: str) -> str | None:
    """빈 값·채워지지 않은 자리표시자(예: 확장 설치 화면에서 비워 둔 ``${user_config.x}``)는 미설정으로 봄."""
    value = (os.environ.get(name) or "").strip()
    if not value or _PLACEHOLDER.match(value):
        return None
    return value


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


@dataclass
class Settings:
    stata_exe: str | None
    backend: str
    default_project: str | None
    max_output_chars: int
    mask_small_cells: int
    unique_ratio: float
    batch_timeout: int
    editor: str
    report_dir: Path
    stata_version: int | None

    @classmethod
    def from_env(cls) -> "Settings":
        ver = _env("STATA_AGENT_STATA_VERSION")
        return cls(
            stata_exe=_env("STATA_AGENT_STATA_EXE"),
            backend=(_env("STATA_AGENT_BACKEND") or "auto").lower(),
            default_project=_env("STATA_AGENT_PROJECT"),
            max_output_chars=_int("STATA_AGENT_MAX_OUTPUT_CHARS", 20_000),
            mask_small_cells=_int("STATA_AGENT_MASK_SMALL_CELLS", 0),
            unique_ratio=_float("STATA_AGENT_UNIQUE_RATIO", 0.9),
            batch_timeout=_int("STATA_AGENT_BATCH_TIMEOUT", 3600),
            editor=(_env("STATA_AGENT_EDITOR") or "doedit").lower(),
            report_dir=Path(_env("STATA_AGENT_REPORT_DIR") or (Path.home() / "Documents" / "StataAgent")),
            stata_version=int(ver) if ver and ver.isdigit() else None,
        )
