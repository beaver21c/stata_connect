"""배치 백엔드: ``Stata*.exe /e do file.do``(Windows) / ``stata -b do file.do``(Unix·Mac).

- COM 미등록(관리자 권한 없음) 환경의 대체 경로이자, 최종 재현 검증(stata_reproduce) 전용 경로
- 호출마다 새 Stata 프로세스 → 메모리(자료·추정결과) 미유지
- 배치 로그는 현재 폴더에 do-file 이름으로 생성됨(설계서 §2.1 1차 확인) → 분석 로그와 충돌하지 않도록
  ``.stata-agent/batch/_batch_*.do`` 래퍼를 실행
- 종료코드는 오류여도 0이라는 보고가 있어(2차 자료) 로그의 ``r(#);``로 판정
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from ..discovery import batch_command
from ..guard.output_filter import last_return_code
from .base import Backend, RunOutcome, stata_path

BATCH_REFUSED = "request ignored because of batch mode"


class BatchBackend(Backend):
    name = "batch_cli"
    persistent_session = False

    def __init__(self, exe: str | None, timeout: int = 3600):
        self.exe = exe
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        if not self.exe:
            return False, "Stata 실행파일을 찾지 못함(STATA_AGENT_STATA_EXE로 지정 가능)"
        if not Path(self.exe).is_file():
            return False, f"Stata 실행파일 없음: {self.exe}"
        return True, ""

    def _batch_dir(self, project_root: Path) -> Path:
        d = Path(project_root) / ".stata-agent" / "batch"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _execute(self, wrapper: Path) -> RunOutcome:
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        log = wrapper.with_suffix(".log")
        log.unlink(missing_ok=True)
        try:
            subprocess.run(batch_command(self.exe, wrapper.name), cwd=wrapper.parent,
                           timeout=self.timeout, capture_output=True, check=False)
        except subprocess.TimeoutExpired:
            return RunOutcome(False, log_path=log, message=f"배치 실행 시간 초과({self.timeout}초)")
        except OSError as e:
            return RunOutcome(False, message=f"배치 실행 실패: {e}")
        if not log.is_file():
            return RunOutcome(False, message="배치 로그 미생성(작업 폴더 쓰기 권한 확인)")
        text = log.read_text(encoding="utf-8", errors="replace")
        if BATCH_REFUSED in text:
            return RunOutcome(False, log_text=text, log_path=log,
                              message="배치 실행 거부: 라이선스 만료·초기화 대화상자 가능성(doctor로 확인)")
        rc = last_return_code(text)
        return RunOutcome(rc == 0, rc, text, log, "" if rc == 0 else f"Stata 오류 r({rc})")

    def open_session(self, project_root: Path, session_id: str) -> RunOutcome:
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        return RunOutcome(True, 0, message="배치 모드: 세션 없음(호출마다 새 Stata 실행, 메모리 미유지)")

    def run_code(self, code: str, session_id: str, project_root: Path) -> RunOutcome:
        d = self._batch_dir(project_root)
        wrapper = d / f"_batch_code_{time.strftime('%Y%m%d_%H%M%S')}.do"
        wrapper.write_text(f'cd "{stata_path(project_root)}"\n{code.rstrip()}\n', encoding="utf-8")
        return self._execute(wrapper)

    def run_dofile(self, path: Path, session_id: str, project_root: Path) -> RunOutcome:
        d = self._batch_dir(project_root)
        wrapper = d / f"_batch_{Path(path).stem}.do"
        wrapper.write_text(
            f'cd "{stata_path(project_root)}"\ndo "{stata_path(path)}"\n', encoding="utf-8"
        )
        return self._execute(wrapper)
