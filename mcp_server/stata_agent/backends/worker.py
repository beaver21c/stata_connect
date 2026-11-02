"""자식 프로세스 작업자 공통부(SPSS 엔진·pystata 백엔드 공용).

방식: 서버가 작업자 스크립트를 파일로 써서 지정 Python으로 띄움 → 표준입력으로 JSON 요청 1줄씩 전달 →
작업자는 응답을 요청이 지정한 파일에 JSON으로 쓰고 표준출력에는 완료 표지 한 줄만 씀
(통계 프로그램이 표준출력에 내보내는 잡음과 섞이지 않게 하기 위함).

표지: ``__SA_READY__``(기동 완료) / ``__SA_FAIL__ 사유``(기동 실패) / ``__SA_DONE__ 요청번호``(요청 완료)
- 시간 초과 시 작업자를 종료(세션 소실) → 다음 요청에서 자동 재기동
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class WorkerError(RuntimeError):
    pass


class JsonWorker:
    """하위 클래스가 ``command()``(실행할 명령 목록)를 정의."""

    label = "작업자"
    start_hint = "설치 경로 확인"

    def __init__(self, work_dir: Path, start_timeout: float = 180.0, request_timeout: float = 900.0):
        self.work_dir = Path(work_dir)
        self.start_timeout = start_timeout
        self.request_timeout = request_timeout
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._next_id = 1
        self.last_error: str | None = None

    def command(self) -> list[str]:
        raise NotImplementedError

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
            self.work_dir.mkdir(parents=True, exist_ok=True)
            cmd = self.command()
            self._lines = queue.Queue()
            try:
                self._proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", cwd=str(self.work_dir),
                )
            except OSError as e:
                raise WorkerError(f"{self.label} 실행 실패({cmd[0]}): {e}") from e
            threading.Thread(target=self._reader, args=(self._proc.stdout,), daemon=True).start()
            deadline = time.monotonic() + self.start_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.stop()
                    raise WorkerError(f"{self.label} 기동 시간 초과({self.start_timeout:.0f}초)")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    continue
                if line == "__SA_READY__":
                    return
                if line.startswith("__SA_FAIL__") or line == "__SA_EOF__":
                    detail = line.replace("__SA_FAIL__", "").strip() or "프로세스 종료"
                    self.stop()
                    self.last_error = detail
                    raise WorkerError(f"{self.label} 기동 실패({self.start_hint}): {detail}")

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
            fd, resp = tempfile.mkstemp(prefix=f"sa_resp_{rid}_", suffix=".json", dir=self.work_dir)
            os.close(fd)
            os.unlink(resp)
            req = {"id": rid, "op": op, "resp": resp, **payload}
            try:
                assert self._proc and self._proc.stdin
                # ASCII 이스케이프 JSON → 작업자 쪽 표준입력 인코딩(Windows cp949 등)과 무관하게 전달
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
            except Exception as e:
                self.stop()
                raise WorkerError(f"{self.label} 요청 전송 실패: {e}") from e
            deadline = time.monotonic() + (timeout or self.request_timeout)
            marker = f"__SA_DONE__ {rid}"
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.stop()
                    raise WorkerError(f"{self.label} 실행 시간 초과 → 작업자 종료(세션 상태 소실, 다음 요청에서 재기동)")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    continue
                if line == marker:
                    break
                if line == "__SA_EOF__":
                    self.stop()
                    raise WorkerError(f"{self.label} 작업자가 비정상 종료됨(세션 상태 소실)")
            try:
                return json.loads(Path(resp).read_text(encoding="utf-8"))
            finally:
                Path(resp).unlink(missing_ok=True)
