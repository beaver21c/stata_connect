"""macOS AppleScript 백엔드(후순위·미구현).

근거: Stata 13부터 AppleScript ``DoCommand``/``DoCommandAsync`` 지원 사례 존재(설계서 §3, 2차 자료).
실기 검증 전까지는 batch_cli로 대체함(설계서 §5 백엔드 선택 규칙).
"""

from __future__ import annotations

from pathlib import Path

from .base import Backend, RunOutcome

_MSG = "macOS AppleScript 백엔드 미구현(후순위) → batch_cli 사용"


class AppleScriptBackend(Backend):
    name = "applescript_mac"
    persistent_session = False

    def available(self) -> tuple[bool, str]:
        return False, _MSG

    def open_session(self, project_root: Path, session_id: str) -> RunOutcome:
        return RunOutcome(False, message=_MSG)

    def run_code(self, code: str, session_id: str, project_root: Path) -> RunOutcome:
        return RunOutcome(False, message=_MSG)

    def run_dofile(self, path: Path, session_id: str, project_root: Path) -> RunOutcome:
        return RunOutcome(False, message=_MSG)
