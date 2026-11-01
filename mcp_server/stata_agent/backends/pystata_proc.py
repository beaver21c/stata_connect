"""pystata 백엔드(보조·선택) — StataCorp 공식 pystata를 별도 Python 자식 프로세스에서 실행.

위치(2026-11-01 사용자 결정 "pystata 방식을 추가하되 주력은 아님"): 주력은 Stata 창 연동(com_gui).
이 백엔드는 ``STATA_AGENT_BACKEND=pystata``로 지정할 때만 사용하고 자동 선택하지 않음.

특징
- 화면 없음: 연구자가 창에서 조작할 수 없으므로 연구자 조작 감지(§14)는 하지 않음
- 호출 간 자료·추정결과 유지(배치와 달리), Windows·macOS·Linux 공통
- 서버 실행파일에 묶인 Python이 아니라 연구자 PC의 Python에서 실행(``STATA_AGENT_PYTHON`` 또는 자동 탐지)
- 통신: JsonWorker(요청 JSON·응답 파일·완료 표지). Stata 출력은 버리고 Stata 로그 파일(log using)로만 읽음
  → MCP 통신 경로와 섞이지 않고, AI 반환은 다른 백엔드와 같이 출력 필터를 거침

근거 지위
- stata_setup.config(path, edition, splash): ``<path>/utilities``를 sys.path에 넣고
  ``pystata.config.init(edition, splash=...)`` 호출, edition은 mp·se·be [1차 확인: stata_setup 0.1.3 소스]
  → 작업자는 stata_setup 설치 없이 같은 두 단계를 직접 수행
- 명령 실패 시 ``SystemError``, 여러 줄 코드는 임시 do-file로 한 번에 실행, ``run()``만 쓰면 numpy·pandas 불필요,
  Stata 17 문서 기준 Python 2.7·3.4 이상, ``config.set_graph_show`` 존재 [2차 확인: stata.com pystata17·18 문서 검색 요약,
  이 환경에서 원문 접속 차단]
- Stata 출력이 Python 표준출력으로 나가는지, 일반 스크립트에서 ``graph export`` 동작, 자식 프로세스·라이선스 제약
  [미확인: 실기 확인 필요, IMPLEMENTATION_STATUS §16]
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from ..discovery import _edition_from_exe, _version_from_path
from ..guard.output_filter import last_return_code
from .base import Backend, RunOutcome, stata_path
from .worker import JsonWorker, WorkerError

MIN_PYSTATA_MAJOR = 17

# Python 2.7·3.4에서도 돌도록 작성(f-문자열·형 주석 금지) — Stata 17 pystata 지원 범위 [2차 확인]
WORKER_SCRIPT = r'''# -*- coding: utf-8 -*-
import sys, os, json, traceback

STATA_HOME = sys.argv[1]
EDITION = sys.argv[2]

# 완료 표지 전용 통로를 따로 두고, 표준출력(1번)은 버림 → Stata·pystata가 화면에 쓰는 내용과 섞이지 않음
_out = os.fdopen(os.dup(1), "wb", 0)
_null = os.open(os.devnull, os.O_WRONLY)
os.dup2(_null, 1)
sys.stdout = open(os.devnull, "w")


def signal(text):
    _out.write(text.encode("ascii", "backslashreplace") + b"\n")
    _out.flush()


def _write(path, obj):
    f = open(path, "wb")
    try:
        f.write(json.dumps(obj).encode("ascii"))
    finally:
        f.close()


try:
    _util = os.path.join(STATA_HOME, "utilities")
    if not os.path.isdir(os.path.join(_util, "pystata")):
        raise RuntimeError("utilities/pystata not found: " + STATA_HOME)
    sys.path.insert(0, _util)
    from pystata import config
    try:
        config.init(EDITION, splash=False)
    except TypeError:
        config.init(EDITION)
    try:
        config.set_graph_show(False)  # 노트북용 자동 그림 표시 끔(graph export는 별도)
    except Exception:
        pass
    from pystata import stata
except Exception as e:
    signal("__SA_FAIL__ " + repr(e)[:500])
    sys.exit(1)


def _run(cmd, quietly):
    stata.run(cmd, quietly=quietly)


def op_run(req):
    err = None
    try:
        _run("capture log close _sapy", True)
    except Exception:
        pass
    _run('log using "' + req["log"] + '", text replace name(_sapy)', True)
    try:
        if req.get("cwd"):
            _run('cd "' + req["cwd"] + '"', True)
        _run('do "' + req["do"] + '"', False)
    except SystemError as e:  # Stata 명령 오류
        err = repr(e)[:1000]
    except Exception as e:
        err = repr(e)[:1000]
    try:
        _run("capture log close _sapy", True)
    except Exception:
        pass
    return {"ok": err is None, "error": err}


OPS = {"ping": lambda req: {"ok": True}, "run": op_run}
signal("__SA_READY__")

while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue
    if req.get("op") == "exit":
        break
    try:
        result = OPS[req["op"]](req)
    except Exception as e:
        result = {"ok": False, "error": repr(e)[:1000], "trace": traceback.format_exc()[-2000:]}
    try:
        _write(req["resp"], result)
    except Exception as e:
        _write(req["resp"], {"ok": False, "error": "response write failed: " + repr(e)[:500]})
    signal("__SA_DONE__ " + str(req["id"]))
'''


def stata_home_for(exe: str | None) -> Path | None:
    """실행파일 위쪽 폴더 중 ``utilities/pystata``가 있는 곳(Windows는 실행파일 폴더, macOS는 .app 바깥 [미확인])."""
    if not exe:
        return None
    for parent in Path(exe).parents:
        if (parent / "utilities" / "pystata").is_dir():
            return parent
    return None


def _is_store_stub(path: str) -> bool:
    # Windows의 'Microsoft Store 열기' 대리 실행파일(WindowsApps)은 실제 Python이 아님
    return "windowsapps" in path.lower()


def find_python(configured: str | None = None) -> tuple[list[str] | None, str]:
    """(실행 명령, 설명). 순서: STATA_AGENT_PYTHON → (실행파일이 아닐 때) 서버 자신의 Python → py -3 → python3·python."""
    if configured:
        if Path(configured).is_file() or shutil.which(configured):
            return [configured], "STATA_AGENT_PYTHON"
        return None, f"STATA_AGENT_PYTHON 경로 없음: {configured}"
    if not getattr(sys, "frozen", False):
        return [sys.executable], "서버 Python"
    launcher = shutil.which("py")
    if launcher and sys.platform.startswith("win"):
        return [launcher, "-3"], "Python 실행기(py -3)"
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found and not _is_store_stub(found):
            return [found], name
    return None, "Python을 찾지 못함 → python.org에서 설치하거나 STATA_AGENT_PYTHON으로 지정"


class PystataWorker(JsonWorker):
    label = "pystata"
    start_hint = "Stata 라이선스·Python·utilities/pystata 확인"

    def __init__(self, python: list[str], stata_home: Path, edition: str, work_dir: Path,
                 start_timeout: float = 180.0, request_timeout: float = 3600.0):
        super().__init__(work_dir, start_timeout, request_timeout)
        self.python, self.stata_home, self.edition = python, stata_home, edition

    def command(self) -> list[str]:
        script = self.work_dir / "sa_pystata_worker.py"
        script.write_text(WORKER_SCRIPT, encoding="utf-8")
        return [*self.python, str(script), str(self.stata_home), self.edition]


class PystataBackend(Backend):
    name = "pystata"
    persistent_session = True
    human_window = False  # 화면 없음 → 연구자 조작 감지 대상 아님

    def __init__(self, stata_exe: str | None, python: str | None = None, timeout: int = 3600,
                 worker_factory=None):
        self.exe = stata_exe
        self.python_setting = python
        self.timeout = timeout
        self.worker_factory = worker_factory or PystataWorker
        self.worker: JsonWorker | None = None
        self._count = 0

    @property
    def edition(self) -> str:
        ed = (_edition_from_exe(Path(self.exe).name) if self.exe else None) or "BE"
        return {"IC": "be"}.get(ed.upper(), ed.lower())

    def available(self) -> tuple[bool, str]:
        if not self.exe:
            return False, "Stata 실행파일을 찾지 못함(STATA_AGENT_STATA_EXE로 지정 가능)"
        major = _version_from_path(self.exe)
        if major is not None and major < MIN_PYSTATA_MAJOR:
            return False, f"pystata는 Stata 17 이상 필요(탐지 버전 {major})"
        if stata_home_for(self.exe) is None:
            return False, f"Stata 폴더에 utilities/pystata 없음({Path(self.exe).parent})"
        python, why = find_python(self.python_setting)
        if python is None:
            return False, why
        return True, f"Python: {why}"

    def _work_dir(self, project_root: Path) -> Path:
        d = Path(project_root) / ".stata-agent" / "pystata"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ensure_worker(self, project_root: Path) -> JsonWorker:
        if self.worker is None:
            python, _ = find_python(self.python_setting)
            home = stata_home_for(self.exe)
            if python is None or home is None:
                raise WorkerError(self.available()[1])
            self.worker = self.worker_factory(python, home, self.edition, self._work_dir(project_root),
                                              request_timeout=float(self.timeout))
        return self.worker

    def _execute(self, do_path: Path, project_root: Path) -> RunOutcome:
        ok, why = self.available()
        if not ok:
            return RunOutcome(False, message=why)
        self._count += 1
        log = self._work_dir(project_root) / f"_run_{self._count:04d}.log"
        log.unlink(missing_ok=True)
        try:
            resp = self._ensure_worker(project_root).request(
                "run", do=stata_path(do_path), log=stata_path(log), cwd=stata_path(project_root))
        except WorkerError as e:
            return RunOutcome(False, message=str(e))
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        rc = last_return_code(text)
        if rc == 0 and not resp.get("ok"):
            rc = None  # Stata 로그에 오류 번호가 없는 실패(작업자 예외)
        ok = rc == 0 and bool(resp.get("ok"))
        msg = "" if ok else (f"Stata 오류 r({rc})" if rc else f"pystata 실행 실패: {resp.get('error') or '원인 미상'}")
        return RunOutcome(ok, rc, text, log, msg)

    def open_session(self, project_root: Path, session_id: str) -> RunOutcome:
        init = self._work_dir(project_root) / "session_init.do"
        init.write_text('display "stata-agent session ready"\ndisplay "SA_VERSION|" c(stata_version)\n',
                        encoding="utf-8")
        out = self._execute(init, project_root)
        if out.ok:
            out.message = "pystata 세션(화면 없음, 보조 백엔드)"
        return out

    def run_code(self, code: str, session_id: str, project_root: Path) -> RunOutcome:
        d = self._work_dir(project_root)
        path = d / f"_code_{time.strftime('%Y%m%d_%H%M%S')}_{self._count + 1:04d}.do"
        path.write_text(code.rstrip() + "\n", encoding="utf-8")
        try:
            return self._execute(path, project_root)
        finally:
            path.unlink(missing_ok=True)

    def run_dofile(self, path: Path, session_id: str, project_root: Path) -> RunOutcome:
        return self._execute(Path(path), project_root)

    def show_in_editor(self, path: Path, session_id: str) -> RunOutcome:
        return RunOutcome(False, message="pystata 백엔드는 화면이 없어 Do-file Editor 연동 불가 → 연구자가 파일을 직접 열 것")

    def break_execution(self, session_id: str) -> RunOutcome:
        return RunOutcome(False, message=(
            "pystata 실행 중단: 서버가 작업자 프로세스를 종료하는 방식만 가능(자료·추정결과 소실). "
            f"제한 시간({self.timeout}초)을 넘으면 자동 종료되고 다음 요청에서 새로 시작함."))

    def close(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None

    def status(self) -> dict:
        base = super().status()
        base["edition"] = self.edition
        base["worker_running"] = bool(self.worker and self.worker.alive)
        base["note"] = "보조 백엔드(화면 없음). 주력은 Stata 창 연동"
        return base
