"""Do-file Editor 갱신(F3).

현재 방식: 파일 저장 후 ``doedit "경로"`` 재호출.
미확인(Phase 0 실측 대상, 설계서 §14)
- 외부에서 수정한 파일을 편집기가 자동 재로드하는지
- ``doedit`` 재호출 시 기존 탭 갱신인지, 중복 탭 생성인지

실측 결과에 따라 strategy를 바꿀 수 있도록 분리함.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .backends.base import Backend, RunOutcome

STRATEGIES = ("doedit", "none")


@dataclass
class EditorSync:
    backend: Backend
    strategy: str = "doedit"
    opened: dict[str, int] = field(default_factory=dict)  # 경로 → 표시 요청 횟수

    def show(self, path: Path, session_id: str) -> RunOutcome:
        if self.strategy == "none":
            return RunOutcome(True, 0, message="편집기 연동 끔(STATA_AGENT_EDITOR=none)")
        if not self.backend.persistent_session:
            return RunOutcome(False, message="배치 모드에서는 편집기 연동 불가 → Stata에서 파일을 직접 열 것")
        outcome = self.backend.show_in_editor(path, session_id)
        if outcome.ok:
            key = str(Path(path).resolve())
            self.opened[key] = self.opened.get(key, 0) + 1
            if self.opened[key] > 1:
                outcome.message += f" / 같은 파일 {self.opened[key]}회째 표시 요청 — 탭 중복 여부를 화면에서 확인"
        return outcome
