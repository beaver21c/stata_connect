"""SPSS 엔진 관리(서버 측). SPSS 내장 Python 서브프로세스를 띄우고 JSON 줄 단위로 요청.

- 엔진 1개 = 화면 없는 SPSS 1개 = 세션(자료·변환 상태 유지)
- 재현 확인은 새 엔진을 따로 띄워 깨끗한 상태에서 실행(배치에 해당)
- 시간 초과 시 엔진을 종료(세션 소실) → 다음 요청에서 자동 재기동
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .engine_script import ENGINE_SCRIPT


class EngineError(RuntimeError):
    pass


@dataclass
class EngineConfig:
    python_exe: str
    spss_home: str
    work_dir: Path
    start_timeout: float = 180.0
    request_timeout: float = 900.0


class SpssEngine:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._next_id = 1
        self.last_error: str | None = None

    # ── 수명 ──
    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _reader(self, stream) -> None:
        for line in iter(stream.readline, ""):
            self._lines.put(line.rstrip("\r\n"))
        self._lines.put("__SA_EOF__")

    def start(self) -> None:
        with self._lock:
            if self.alive:
                return
            self.cfg.work_dir.mkdir(parents=True, exist_ok=True)
            script = self.cfg.work_dir / "sa_spss_engine.py"
            script.write_text(ENGINE_SCRIPT, encoding="utf-8")
            self._lines = queue.Queue()
            self._proc = subprocess.Popen(
                [self.cfg.python_exe, str(script), self.cfg.spss_home],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", cwd=str(self.cfg.work_dir),
            )
            threading.Thread(target=self._reader, args=(self._proc.stdout,), daemon=True).start()
            deadline = time.monotonic() + self.cfg.start_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.stop()
                    raise EngineError(f"SPSS 기동 시간 초과({self.cfg.start_timeout:.0f}초)")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    continue
                if line == "__SA_READY__":
                    return
                if line.startswith("__SA_FAIL__") or line == "__SA_EOF__":
                    detail = line.replace("__SA_FAIL__", "").strip() or "프로세스 종료"
                    self.stop()
                    raise EngineError(f"SPSS 기동 실패(라이선스·설치 경로 확인): {detail}")

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
            if proc is None:
                return
            try:
                if proc.poll() is None and proc.stdin:
                    proc.stdin.write(json.dumps({"op": "exit"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=10)
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()

    # ── 요청 ──
    def request(self, op: str, timeout: float | None = None, **payload) -> dict:
        with self._lock:
            self.start()
            rid = self._next_id
            self._next_id += 1
            fd, resp = tempfile.mkstemp(prefix=f"sa_resp_{rid}_", suffix=".json", dir=self.cfg.work_dir)
            os.close(fd)
            os.unlink(resp)
            req = {"id": rid, "op": op, "resp": resp, **payload}
            try:
                assert self._proc and self._proc.stdin
                # ASCII 이스케이프 JSON → 엔진 쪽 표준입력 인코딩(Windows cp949 등)과 무관하게 전달
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
            except Exception as e:
                self.stop()
                raise EngineError(f"엔진 요청 전송 실패: {e}") from e
            deadline = time.monotonic() + (timeout or self.cfg.request_timeout)
            marker = f"__SA_DONE__ {rid}"
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.stop()
                    raise EngineError("SPSS 실행 시간 초과 → 엔진 종료(세션 상태 소실, 다음 요청에서 재기동)")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    continue
                if line == marker:
                    break
                if line == "__SA_EOF__":
                    self.stop()
                    raise EngineError("SPSS 엔진이 비정상 종료됨(세션 상태 소실)")
            try:
                return json.loads(Path(resp).read_text(encoding="utf-8"))
            finally:
                Path(resp).unlink(missing_ok=True)
