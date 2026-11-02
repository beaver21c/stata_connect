"""분석·보고용 구분 SPSS판(IMPLEMENTATION_STATUS §20.5)."""

import shutil
import sys
from pathlib import Path

import pytest

from spss_agent.readability import ANALYSIS_NOTE, REPORT_NOTE, REPORT_TAG, decorate_code, readability_notes


@pytest.mark.parametrize("code,kind,expect", [
    ("REGRESSION /STATISTICS COEFF R ANOVA CHANGE /DEPENDENT y /METHOD=ENTER x1 /METHOD=ENTER x2.\n", "analysis", 0),
    ("OMS /SELECT ALL /DESTINATION VIEWER=NO.\nREGR /DEPENDENT y /METHOD=ENTER x1.\nOMSEND.\n", "analysis", 1),
    ("OMS /SELECT ALL /DESTINATION VIEWER=NO.\nOMSEND.\nFREQUENCIES VARIABLES=sex.\n", "analysis", 0),
    ("MATRIX.\nCOMPUTE a = {1, 2}.\nEND MATRIX.\n", "analysis", 1),
    ("MATRIX DATA VARIABLES=ROWTYPE_ x1 x2.\n", "analysis", 0),  # MATRIX DATA는 자료 입력 명령
    ("MATRIX.\nCOMPUTE a = {1, 2}.\nEND MATRIX.\n", "report", 0),
    ("LOGISTIC REGRESSION VARIABLES y /METHOD=ENTER x.\n", "report", 1),
    ("* REGRESSION 주석은 무시.\n", "report", 0),
])
def test_notes_table(code, kind, expect):
    assert len(readability_notes(code, kind)) == expect


def test_notes_are_spss_comments():
    for note in (ANALYSIS_NOTE, REPORT_NOTE):
        assert note.startswith("* ") and note.endswith(".")  # SPSS 주석 명령은 마침표로 끝남
    out = decorate_code(decorate_code("DESCRIPTIVES x.", "analysis"), "report")
    assert out.split("\n")[0] == REPORT_NOTE and out.count("DESCRIPTIVES x.") == 1


@pytest.fixture
def svc(settings, project, tmp_path):
    from spss_agent.backend import SpssBackend
    from spss_agent.discovery import SpssInstall
    from spss_agent.engine import EngineConfig, SpssEngine
    from spss_agent.service import SpssAgentService

    home = tmp_path / "SPSS"
    shutil.copytree(Path(__file__).parent / "fake_spss_home", home)
    (home / "Python3" / "python.exe").write_text("")
    (home / "stats.exe").write_text("")

    def factory(install, work_dir, timeout):
        return SpssEngine(EngineConfig(sys.executable, install.home, work_dir, start_timeout=30, request_timeout=timeout))

    s = SpssAgentService(settings, SpssBackend(SpssInstall(str(home), 27, "user"), 30.0, factory))
    assert not s.open_session(str(project)).is_error
    yield s
    s.backend.close()


def test_spss_write_patch_run(svc, project):
    r = svc.write_syntax("04_reg.sps", [
        {"title": "자료", "code": "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3\nEND DATA.\nEXECUTE."},
        {"title": "표 가공", "kind": "report", "code": "MATRIX.\nCOMPUTE a = {1, 2}.\nEND MATRIX."},
    ])
    assert not r.is_error and "분석 1·보고용 1" in r.text, r.text
    text = (project / "04_reg.sps").read_text(encoding="utf-8-sig")
    assert f"*== [S02] {REPORT_TAG} 표 가공 ==." in text and ANALYSIS_NOTE in text and REPORT_NOTE in text
    run = svc.run_section("04_reg.sps", "S01")  # 안내 주석 줄이 있어도 SPSS 실행 정상
    assert not run.is_error, run.text
    assert svc.run_section("04_reg.sps", "S02").text.startswith("※ 보고용 계산 섹션")
    p = svc.patch_syntax("04_reg.sps", "replace", section_id="S02", code="DESCRIPTIVES x.")
    assert "보고용 섹션에 새 분석 절차" in p.text and f"{REPORT_TAG} 표 가공" in (project / "04_reg.sps").read_text(
        encoding="utf-8-sig")
