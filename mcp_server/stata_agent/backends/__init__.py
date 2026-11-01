"""Stata 실행 백엔드."""

from __future__ import annotations

import sys

from .base import Backend, RunOutcome
from .batch_cli import BatchBackend


def select_backend(preference: str, stata_exe: str | None, python: str | None = None,
                   timeout: int = 3600) -> tuple[Backend, str]:
    """설계서 §5 선택 규칙. (백엔드, 선택 사유) 반환.

    preference: "auto" | "com" | "batch" | "pystata"
    pystata는 보조 백엔드로 지정할 때만 사용(auto에서 고르지 않음, IMPLEMENTATION_STATUS §16)
    """
    batch = BatchBackend(stata_exe)
    if preference == "batch":
        return batch, "설정으로 배치 백엔드 지정"
    if preference == "pystata":
        from .pystata_proc import PystataBackend

        py = PystataBackend(stata_exe, python, timeout)
        ok, why = py.available()
        if ok:
            return py, f"설정으로 pystata 백엔드 지정(화면 없음, {why})"
        return batch, f"pystata 지정됐으나 사용 불가({why}) → 배치 백엔드(기능 축소)"
    if sys.platform.startswith("win"):
        from .com_gui import ComGuiBackend

        com = ComGuiBackend()
        ok, why = com.available()
        if ok:
            return com, "Windows + COM 등록 확인 → 가시 GUI 세션"
        if preference == "com":
            return com, f"COM 지정됐으나 사용 불가: {why}"
        return batch, f"COM 사용 불가({why}) → 배치 백엔드(기능 축소)"
    if sys.platform == "darwin":
        return batch, "macOS: AppleScript 백엔드 미구현 → 배치 백엔드"
    return batch, "Windows 아님 → 배치 백엔드"


__all__ = ["Backend", "BatchBackend", "RunOutcome", "select_backend"]
