"""연구자 요청 원문 기록(IMPLEMENTATION_STATUS §21): 일자·시각 + 원문을 실행되지 않는 주석으로, 수정 때 쌓임."""

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

from fakes import FakeBackend
from stata_agent.request_note import compose, split_requests, spss_block, stata_block
from stata_agent.service import StataAgentService

STAMP = re.compile(r"\(\d{4}-\d{2}-\d{2} \d{2}:\d{2}\)")


def test_stata_block_escapes_comment_markers():
    b = stata_block("회귀해줘 */ 그리고 /* 이것도", datetime(2026, 11, 2, 23, 41))
    assert b[0] == "/* ── 연구자 요청 (2026-11-02 23:41) ──" and b[-1] == "*/"
    assert all("*/" not in ln and "/*" not in ln for ln in b[1:-1])


def test_spss_block_closes_every_line():
    b = spss_block("y를 x로 회귀해줘\n\n표준화 계수도.", datetime(2026, 11, 2, 23, 41))
    assert b == ["* ── 연구자 요청 (2026-11-02 23:41) ──.", "* │ y를 x로 회귀해줘.", "* │ 표준화 계수도."]


def test_compose_stacks_and_dedupes():
    w = datetime(2026, 11, 2, 9, 0)
    old = stata_block("첫 요청", w) + ["regress y x"]
    req, rest = compose(old, "\n".join(stata_block("첫 요청", w) + ["regress y x z"]), "둘째 요청", "stata", w)
    assert req.count("첫 요청") == 1 and req[-2] == "둘째 요청" and rest == "regress y x z"
    assert split_requests(["* ── 연구자 요청 (x) ──.", "* │ a.", "DESCRIPTIVES x."], "spss")[1] == ["DESCRIPTIVES x."]


@pytest.fixture
def svc(settings, project):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False))
    assert not s.open_session(str(project)).is_error
    return s


def test_stata_write_patch_run(svc, project):
    request = "price를 weight로 회귀해줘. 이상치는 list로 보지 말고"
    r = svc.write_dofile("04_reg.do", [{"title": "회귀", "code": "regress price weight", "request": request}])
    assert not r.is_error and "요청 원문 미기록" not in r.text
    text = (project / "04_reg.do").read_text(encoding="utf-8")
    block = text.split("*== [S01] 회귀 ==*")[1]
    assert block.lstrip().startswith("/* ── 연구자 요청 (") and STAMP.search(block) and request in block
    assert block.index("연구자 요청") < block.index("▶ 분석") < block.index("regress price weight")
    run = svc.run_section("04_reg.do", "S01")  # 요청 속 'list'는 주석이라 차단되지 않음
    assert not run.is_error and "차단" not in run.text, run.text
    svc.patch_dofile("04_reg.do", "replace", section_id="S01", code="regress price weight length",
                     request="length도 넣어줘")
    text = (project / "04_reg.do").read_text(encoding="utf-8")
    assert text.count("── 연구자 요청") == 2 and text.index(request) < text.index("length도 넣어줘")
    p = svc.patch_dofile("04_reg.do", "replace", section_id="S01", code="regress price weight length turn")
    assert "요청 원문 미기록" in p.text
    assert (project / "04_reg.do").read_text(encoding="utf-8").count("── 연구자 요청") == 2  # 이전 기록 유지
    hist = (project / ".stata-agent" / "history.jsonl").read_text(encoding="utf-8")
    assert request not in hist and "length도" not in hist  # 사용 기록에는 원문 없음


def test_stata_missing_request_note(svc):
    r = svc.write_dofile("05_x.do", [{"title": "a", "code": "summarize price"}])
    assert "요청 원문 미기록: S01" in r.text


def test_spss_request_recorded_and_runs(settings, project, tmp_path):
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

    svc = SpssAgentService(settings, SpssBackend(SpssInstall(str(home), 27, "user"), 30.0, factory))
    try:
        assert not svc.open_session(str(project)).is_error
        req = "x 기술통계 내줘\nLIST로 사례는 보지 말고"
        r = svc.write_syntax("04_d.sps", [{"title": "기술", "request": req,
                                           "code": "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3\nEND DATA.\nDESCRIPTIVES VARIABLES=x."}])
        assert not r.is_error and "요청 원문 미기록" not in r.text, r.text
        text = (project / "04_d.sps").read_text(encoding="utf-8-sig")
        assert "* ── 연구자 요청 (" in text and "* │ x 기술통계 내줘." in text and "* │ LIST로 사례는 보지 말고." in text
        run = svc.run_section("04_d.sps", "S01")  # 요청 속 LIST는 주석이라 차단되지 않음
        assert not run.is_error and "차단" not in run.text, run.text
        svc.patch_syntax("04_d.sps", "replace", section_id="S01",
                         code="DATA LIST FREE / x.\nBEGIN DATA\n1 2 3\nEND DATA.\nFREQUENCIES VARIABLES=x.", request="빈도표로 바꿔줘")
        assert (project / "04_d.sps").read_text(encoding="utf-8-sig").count("── 연구자 요청") == 2
    finally:
        svc.backend.close()
