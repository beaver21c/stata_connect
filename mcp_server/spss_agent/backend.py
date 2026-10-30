"""SPSS 백엔드: 엔진(세션) 1개를 감싸 실행·출력 수집·사전(dictionary)·고유값 조회 제공."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from stata_agent.backends.base import RunOutcome, stata_path

from .discovery import SpssInstall
from .engine import EngineConfig, EngineError, SpssEngine


class EngineLike(Protocol):
    alive: bool

    def start(self) -> None: ...
    def request(self, op: str, timeout: float | None = None, **payload) -> dict: ...
    def stop(self) -> None: ...


def default_engine_factory(install: SpssInstall, work_dir: Path, timeout: float) -> EngineLike:
    return SpssEngine(EngineConfig(str(install.python_exe), install.home, work_dir, request_timeout=timeout))


class SpssBackend:
    name = "spss_engine"

    def __init__(self, install: SpssInstall | None, timeout: float = 900.0,
                 engine_factory: Callable[[SpssInstall, Path, float], EngineLike] = default_engine_factory):
        self.install = install
        self.timeout = timeout
        self.engine_factory = engine_factory
        self.engine: EngineLike | None = None
        self.root: Path | None = None

    def available(self) -> tuple[bool, str]:
        if self.install is None:
            return False, "SPSS Statistics 설치를 찾지 못함(SPSS_AGENT_HOME으로 설치 폴더 지정 가능)"
        if not self.install.python_ready:
            return False, f"SPSS 내장 Python 없음: {self.install.python_exe} (Python 연동 기능 설치 확인)"
        return True, ""

    def fresh(self) -> "SpssBackend":
        """재현 확인용 새 엔진(깨끗한 상태)."""
        return SpssBackend(self.install, self.timeout, self.engine_factory)

    def open_session(self, root: Path, engine_dir: str = ".spss-agent/engine") -> RunOutcome:
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        if self.engine is None or self.root != root:
            self.close()
            self.engine = self.engine_factory(self.install, Path(root) / engine_dir, self.timeout)  # type: ignore[arg-type]
            self.root = Path(root)
        try:
            self.engine.start()
            r = self.engine.request("submit", syntax=f"CD '{stata_path(root)}'.",
                                    outfile=str(Path(root) / engine_dir / "cd.txt"))
        except EngineError as e:
            return RunOutcome(False, message=str(e))
        if not r.get("ok"):
            return RunOutcome(False, message=f"작업 폴더 설정 실패: {r.get('error') or r}")
        return RunOutcome(True, 0, message="SPSS 엔진 준비")

    def _engine(self) -> EngineLike:
        if self.engine is None:
            raise EngineError("세션 없음 → spss_open_session 먼저 실행")
        return self.engine

    def run(self, syntax: str, outfile: Path) -> RunOutcome:
        outfile.parent.mkdir(parents=True, exist_ok=True)
        outfile.unlink(missing_ok=True)
        try:
            r = self._engine().request("submit", syntax=syntax, outfile=str(outfile))
        except EngineError as e:
            return RunOutcome(False, None, "", outfile, str(e))
        text = outfile.read_text(encoding="utf-8-sig", errors="replace") if outfile.is_file() else ""
        level = r.get("err_level")
        msg = ""
        if r.get("error"):
            msg = f"SPSS 오류: {r['error']}"
        elif level and level >= 3:
            msg = f"SPSS 오류 수준 {level}(3 이상: 심각한 오류)"
        elif level == 2:
            msg = "SPSS 경고 있음(출력 확인)"
        return RunOutcome(bool(r.get("ok")), level, text, outfile, msg)

    def dictionary(self, missing: bool = True) -> dict:
        return self._engine().request("dictionary", missing=missing)

    def unique(self, tokens: list[str]) -> dict:
        return self._engine().request("unique", tokens=tokens)

    def close(self) -> None:
        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception:
                pass
        self.engine = None

    def status(self) -> dict:
        ok, why = self.available()
        return {
            "backend": self.name, "available": ok, "reason": why,
            "install": self.install.public_dict() if self.install else None,
            "engine_running": bool(self.engine and self.engine.alive),
            "project": str(self.root) if self.root else None,
        }
