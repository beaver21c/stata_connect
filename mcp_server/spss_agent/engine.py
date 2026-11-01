"""SPSS 엔진 관리(서버 측). SPSS 내장 Python 서브프로세스를 띄우고 JSON 줄 단위로 요청.

- 엔진 1개 = 화면 없는 SPSS 1개 = 세션(자료·변환 상태 유지)
- 재현 확인은 새 엔진을 따로 띄워 깨끗한 상태에서 실행(배치에 해당)
- 시간 초과 시 엔진을 종료(세션 소실) → 다음 요청에서 자동 재기동
- 통신 방식(요청 JSON·응답 파일·완료 표지)은 stata_agent.backends.worker.JsonWorker 공용(pystata 백엔드와 같음)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stata_agent.backends.worker import JsonWorker, WorkerError

from .engine_script import ENGINE_SCRIPT

EngineError = WorkerError


@dataclass
class EngineConfig:
    python_exe: str
    spss_home: str
    work_dir: Path
    start_timeout: float = 180.0
    request_timeout: float = 900.0


class SpssEngine(JsonWorker):
    label = "SPSS"
    start_hint = "라이선스·설치 경로 확인"

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        super().__init__(cfg.work_dir, cfg.start_timeout, cfg.request_timeout)

    def command(self) -> list[str]:
        script = self.cfg.work_dir / "sa_spss_engine.py"
        script.write_text(ENGINE_SCRIPT, encoding="utf-8")
        return [self.cfg.python_exe, str(script), self.cfg.spss_home]
