"""백엔드 공통 인터페이스.

백엔드 선택 규칙(설계서 §5)
- Windows + COM 등록 + pywin32 → com_gui(대화형·가시 GUI 세션)
- 그 밖 → batch_cli(호출 간 메모리 미유지, 기능 축소)
- 최종 재현 검증 → 항상 batch_cli
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunOutcome:
    ok: bool
    return_code: int | None = None
    log_text: str = ""  # 원 로그(로컬 전용). AI 반환 전 반드시 output_filter 통과
    log_path: Path | None = None
    message: str = ""  # 백엔드 수준 안내·오류


def stata_path(path: Path | str) -> str:
    """Stata 명령에 넣을 경로(역슬래시 → 슬래시)."""
    return str(path).replace("\\", "/")


class Backend(ABC):
    name: str = "base"
    persistent_session: bool = False  # 호출 간 메모리(자료·추정결과) 유지 여부

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(사용 가능 여부, 사유)."""

    @abstractmethod
    def open_session(self, project_root: Path, session_id: str) -> RunOutcome: ...

    @abstractmethod
    def run_code(self, code: str, session_id: str, project_root: Path) -> RunOutcome: ...

    @abstractmethod
    def run_dofile(self, path: Path, session_id: str, project_root: Path) -> RunOutcome: ...

    def show_in_editor(self, path: Path, session_id: str) -> RunOutcome:
        return RunOutcome(False, message=f"{self.name} 백엔드는 Do-file Editor 연동을 지원하지 않음")

    def break_execution(self, session_id: str) -> RunOutcome:
        return RunOutcome(
            False,
            message=(
                "실행 중단 도구 미구현: 래퍼 구조상 실행 중인 COM 호출에 끼어들 통로가 없고, "
                "UtilSetStataBreak가 동기 DoCommand를 중단하는지 미확인(Phase 0 실측 대상). "
                "Stata 창의 Break 버튼(또는 Ctrl+Break)을 사용하도록 연구자에게 안내할 것."
            ),
        )

    def status(self) -> dict:
        ok, why = self.available()
        return {"backend": self.name, "available": ok, "reason": why, "persistent_session": self.persistent_session}
