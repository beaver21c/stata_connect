"""pystata 백엔드(보조, IMPLEMENTATION_STATUS §16): 탐지·작업자 통신·세션 유지·오류·그래프·서비스 연동.

가짜 pystata(tests/fake_stata_home/utilities/pystata, StataCorp 제품 아님)를 실제 자식 프로세스로 띄워 검증.
"""

import shutil
import sys
from pathlib import Path

import pytest

from stata_agent.backends import BatchBackend, select_backend
from stata_agent.backends.pystata_proc import WORKER_SCRIPT, PystataBackend, find_python, stata_home_for
from stata_agent.service import StataAgentService

FAKE = Path(__file__).parent / "fake_stata_home"


@pytest.fixture
def stata_home(tmp_path):
    home = tmp_path / "Stata18"
    shutil.copytree(FAKE, home)
    exe = home / "StataSE-64.exe"
    exe.write_text("")
    return home, str(exe)


@pytest.fixture
def backend(stata_home):
    _, exe = stata_home
    b = PystataBackend(exe, timeout=60)
    yield b
    b.close()


def test_discovery_rules(stata_home, tmp_path):
    home, exe = stata_home
    assert stata_home_for(exe) == home
    b = PystataBackend(exe)
    assert b.edition == "se" and b.available()[0]
    old = tmp_path / "Stata16"
    old.mkdir()
    (old / "StataMP-64.exe").write_text("")
    assert "17 이상" in PystataBackend(str(old / "StataMP-64.exe")).available()[1]
    bare = tmp_path / "Stata17"
    bare.mkdir()
    (bare / "StataBE-64.exe").write_text("")
    assert "utilities/pystata" in PystataBackend(str(bare / "StataBE-64.exe")).available()[1]
    assert find_python(str(tmp_path / "none.exe"))[0] is None
    assert find_python()[0] == [sys.executable]  # 실행파일 묶음이 아닐 때는 서버 자신의 Python


def test_select_backend_only_when_requested(stata_home, tmp_path):
    _, exe = stata_home
    b, why = select_backend("pystata", exe)
    assert isinstance(b, PystataBackend) and "pystata" in why
    b2, why2 = select_backend("pystata", str(tmp_path / "Stata18x" / "StataSE-64.exe"))
    assert isinstance(b2, BatchBackend) and "사용 불가" in why2
    b3, _ = select_backend("auto", exe)
    assert not isinstance(b3, PystataBackend)  # 자동 선택하지 않음(보조 백엔드)


def test_worker_roundtrip_session_and_errors(backend, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    out = backend.open_session(root, "s")
    assert out.ok and "SA_VERSION|18" in out.log_text, out.message
    assert backend.run_code("scalar keep = 7", "s", root).ok
    kept = backend.run_code("display scalar(keep)", "s", root)
    assert kept.ok and "\n7\n" in kept.log_text  # 호출 간 상태 유지(배치와 다름)
    err = backend.run_code('display "a"\nforce_error', "s", root)
    assert not err.ok and err.return_code == 111 and "r(111)" in err.message
    assert backend.run_code('display "after error"', "s", root).ok  # 오류 뒤에도 세션 유지
    assert not list((root / ".stata-agent" / "pystata").glob("_code_*.do"))  # 임시 do-file 정리


def test_worker_start_failure_reported(stata_home, tmp_path, monkeypatch):
    _, exe = stata_home
    monkeypatch.setenv("FAKE_PYSTATA_FAIL", "1")
    b = PystataBackend(exe, timeout=30)
    root = tmp_path / "proj"
    root.mkdir()
    out = b.open_session(root, "s")
    assert not out.ok and "기동 실패" in out.message and "license" in out.message
    b.close()


def test_service_with_pystata(settings, project, backend):
    svc = StataAgentService(settings, backend=backend, batch=BatchBackend(None))
    r = svc.open_session(str(project))
    assert not r.is_error and "pystata" in r.text, r.text
    assert not (project / ".stata-agent" / "cmdlog.txt").exists()  # 화면 없음 → 연구자 조작 감지 생략
    assert "화면 없는 세션" in svc.check_changes().text
    svc.write_dofile("01_fig.do", [{"title": "그림", "code": 'display "hello"\n'
                                    'graph export "output/figures/h.png", replace'}])
    run = svc.run_section("01_fig.do", "S01")
    assert not run.is_error and "hello" in run.text, run.text
    assert (project / "output" / "figures" / "h.png").is_file()
    # 메모리 그래프: 출처 판정이 없으면 승인 필요, 승인 후 내보내기 → 이미지
    v = svc.view_graph(acknowledge_risks=True)
    assert not v.is_error and v.images and v.images[0][0].startswith(b"\x89PNG"), v.text
    assert "Do-file Editor 연동 불가" in svc.show_in_editor("01_fig.do").text


def test_worker_script_py2_compatible_names():
    assert "f\"" not in WORKER_SCRIPT and "f'" not in WORKER_SCRIPT
    assert "config.init(EDITION, splash=False)" in WORKER_SCRIPT and "except SystemError" in WORKER_SCRIPT
