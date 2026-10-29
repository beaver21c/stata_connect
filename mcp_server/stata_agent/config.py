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
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
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
        ver = os.environ.get("STATA_AGENT_STATA_VERSION")
        return cls(
            stata_exe=os.environ.get("STATA_AGENT_STATA_EXE") or None,
            backend=(os.environ.get("STATA_AGENT_BACKEND") or "auto").lower(),
            default_project=os.environ.get("STATA_AGENT_PROJECT") or None,
            max_output_chars=_int("STATA_AGENT_MAX_OUTPUT_CHARS", 20_000),
            mask_small_cells=_int("STATA_AGENT_MASK_SMALL_CELLS", 0),
            unique_ratio=_float("STATA_AGENT_UNIQUE_RATIO", 0.9),
            batch_timeout=_int("STATA_AGENT_BATCH_TIMEOUT", 3600),
            editor=(os.environ.get("STATA_AGENT_EDITOR") or "doedit").lower(),
            report_dir=Path(os.environ.get("STATA_AGENT_REPORT_DIR") or (Path.home() / "Documents" / "StataAgent")),
            stata_version=int(ver) if ver and ver.isdigit() else None,
        )
