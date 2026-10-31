"""SPSS 22 호환 검사(IMPLEMENTATION_STATUS §13): 설치 경로·내장 Python 선택·지원 범위·출력 인코딩.

근거: 22·23 = Python 2.7, 24~26 = 2.7·3.4, 27부터 3.x만 [2차 확인: IBM 문서 검색 요약].
2.7 폴더 이름(Python)·구버전 경로(IBM\\SPSS\\Statistics\\22)는 [미확인] → 실기 확인 대상.
"""

import shutil
import sys
from pathlib import Path

from spss_agent import discovery
from spss_agent.backend import SpssBackend, read_output
from spss_agent.discovery import SpssInstall, choose, scan
from spss_agent.engine import EngineConfig, SpssEngine
from spss_agent.selftest import run_selftest
from spss_agent.service import SpssAgentService

FAKE_HOME = Path(__file__).parent / "fake_spss_home"


def _home(tmp_path, name, pythons):
    home = tmp_path / name
    (home).mkdir(parents=True)
    (home / "stats.exe").write_text("")
    for d in pythons:
        (home / d).mkdir()
        (home / d / "python.exe").write_text("")
    return home


def test_python_folder_by_version(tmp_path, monkeypatch):
    monkeypatch.delenv("SPSS_AGENT_PYTHON", raising=False)
    v22 = SpssInstall(str(_home(tmp_path, "22", ["Python"])), 22, "scan")
    assert v22.python_exe.parent.name == "Python" and v22.python_line == "2.7" and v22.python_ready
    v25 = SpssInstall(str(_home(tmp_path, "25", ["Python", "Python3"])), 25, "scan")
    assert v25.python_exe.parent.name == "Python3" and v25.python_line == "3.x"  # 3.4 우선
    v22none = SpssInstall(str(_home(tmp_path, "22b", [])), 22, "scan")
    assert not v22none.python_ready and v22none.python_exe.parent.name == "Python"
    custom = tmp_path / "C_Python27" / "python.exe"
    custom.parent.mkdir()
    custom.write_text("")
    monkeypatch.setenv("SPSS_AGENT_PYTHON", str(custom))
    assert v22none.python_exe == custom and v22none.python_ready
    monkeypatch.setenv("SPSS_AGENT_PYTHON", "${user_config.spss_python}")  # 비워 둔 확장 설정
    assert v22none.python_exe.parent.name == "Python"


def test_supported_range_and_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("SPSS_AGENT_PYTHON", raising=False)
    old = SpssInstall(str(_home(tmp_path, "21", ["Python"])), 21, "scan")
    v22 = SpssInstall(str(_home(tmp_path, "22", ["Python"])), 22, "scan")
    assert old.supported is False and v22.supported is True
    assert SpssInstall("x", None, "scan").supported is None
    assert choose([old, v22]) is v22
    assert v22.public_dict()["python_line"] == "2.7" and v22.public_dict()["supported"] is True


def test_scan_old_and_new_layouts(tmp_path):
    root = tmp_path / "Program Files"
    for rel in ("IBM/SPSS/Statistics/22", "IBM/SPSS Statistics/27", "IBM/SPSS Statistics"):
        d = root / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "stats.exe").write_text("")
    found = {(Path(i.home).relative_to(root).as_posix(), i.version) for i in scan([str(root)])}
    assert ("IBM/SPSS/Statistics/22", 22) in found and ("IBM/SPSS Statistics/27", 27) in found
    assert ("IBM/SPSS Statistics", None) in found


def test_registry_key_variants_cover_32bit():
    assert any("WOW6432Node" in k for k in discovery.REGISTRY_KEYS)
    assert r"SOFTWARE\IBM\SPSS\Statistics" in discovery.REGISTRY_KEYS


def test_read_output_codepage_fallback(tmp_path, monkeypatch):
    import locale

    p = tmp_path / "o.txt"
    p.write_bytes("기술통계".encode("cp949"))
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp949")
    assert read_output(p) == "기술통계"
    p.write_bytes("﻿기술통계".encode("utf-8"))
    assert read_output(p) == "기술통계"


def test_selftest_t1_fails_below_22(settings, tmp_path, monkeypatch):
    monkeypatch.delenv("SPSS_AGENT_PYTHON", raising=False)
    home = tmp_path / "SPSS21"
    shutil.copytree(FAKE_HOME, home)
    (home / "Python3" / "python.exe").write_text("")
    (home / "stats.exe").write_text("")

    def factory(install, work_dir, timeout):
        return SpssEngine(EngineConfig(sys.executable, install.home, work_dir, start_timeout=30, request_timeout=timeout))

    svc = SpssAgentService(settings, SpssBackend(SpssInstall(str(home), 21, "user"), 30.0, factory))
    try:
        results, _ = run_selftest(svc, "test", include_batch=False, release_lookup=lambda: "v0.1.0")
    finally:
        svc.backend.close()
    t1 = next(r for r in results if r.id == "T1")
    assert t1.status == "fail" and "22" in t1.remedy


def test_export_docx_becomes_doc_on_22(settings, project, tmp_path, monkeypatch):
    """SPSS 27 이하 OMS FORMAT=DOC는 .doc 형식 [2차 확인] → .docx 요청을 .doc로 저장하고 알림."""
    monkeypatch.delenv("SPSS_AGENT_PYTHON", raising=False)
    home = tmp_path / "SPSS22"
    shutil.copytree(FAKE_HOME, home)
    (home / "Python3" / "python.exe").write_text("")
    (home / "stats.exe").write_text("")

    def factory(install, work_dir, timeout):
        return SpssEngine(EngineConfig(sys.executable, install.home, work_dir, start_timeout=30, request_timeout=timeout))

    svc = SpssAgentService(settings, SpssBackend(SpssInstall(str(home), 22, "user"), 30.0, factory))
    try:
        assert not svc.open_session(str(project)).is_error
        svc.write_syntax("01_desc.sps", [
            {"title": "자료", "code": "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3 4\nEND DATA.\nCOMPUTE y = x*x.\nEXECUTE."},
            {"title": "상관", "code": "CORRELATIONS /VARIABLES=x y."},
        ])
        svc.run_section("01_desc.sps", "S01")
        r = svc.export("01_desc.sps", "S02", "table1.docx")
        assert not r.is_error and ".doc" in r.text and (project / "output/tables/table1.doc").is_file(), r.text
        assert not (project / "output/tables/table1.docx").exists()
        r2 = svc.export("01_desc.sps", "S02", "table1.xls")
        assert not r2.is_error and (project / "output/tables/table1.xls").is_file()
    finally:
        svc.backend.close()
