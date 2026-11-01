"""연구자 조작 감지·이어받기(IMPLEMENTATION_STATUS §14): 창 연동 중 사람이 바꾼 자료·명령·do-file을 AI가 알아챔."""

import pytest

from fakes import FakeBackend
from stata_agent.service import StataAgentService
from stata_agent.sync import DataState, FileWatch, diff_states, parse_state, state_code
from stata_agent.dofile import DoFile


def _st(vars_, n=74, sig=None, f="auto.dta"):
    return DataState(n, len(vars_), f, vars_, sig or {v[0]: f"s-{v[0]}" for v in vars_})


BASE = [("make", "str18", ""), ("price", "int", ""), ("mpg", "int", ""), ("foreign", "byte", "origin")]


def test_diff_rename_recode_drop_add():
    old = _st(BASE)
    renamed = [("make", "str18", ""), ("cost", "int", ""), ("mpg", "int", ""), ("foreign", "byte", "origin")]
    sig = {"make": "s-make", "cost": "s-price", "mpg": "s-mpg-recoded", "foreign": "s-foreign"}
    d = diff_states(old, _st(renamed, sig=sig))
    assert any("이름 변경 추정: price → cost" in x for x in d)
    assert any("값 변경 감지" in x and "mpg" in x and "cost" not in x for x in d)  # 이름만 바뀐 변수는 값 변경 아님
    d2 = diff_states(old, _st(BASE[:3] + [("heavy", "byte", "")]))
    assert any("새 변수: heavy" in x for x in d2) and any("삭제된 변수: foreign" in x for x in d2)
    assert diff_states(old, _st(BASE)) == []
    cleared = diff_states(old, DataState(0, 0, "", [], {}))
    assert any("비워짐" in x for x in cleared) and any("관측치 수 74 → 0" in x for x in cleared)
    other = diff_states(old, _st(BASE, f="C:/x/other.dta"))
    assert any("다른 자료" in x and "other.dta" in x for x in other)
    retyped = diff_states(old, _st([("make", "str18", ""), ("price", "long", ""), ("mpg", "int", ""),
                                    ("foreign", "byte", "")]))
    assert any("유형 변경: price(int→long)" in x for x in retyped) and any("값 라벨 연결 변경: foreign" in x for x in retyped)


def test_state_code_preserves_r_and_parses():
    code = state_code(1000)
    assert "_return hold __sast" in code and "_return restore __sast" in code and "datasignature" in code
    assert "datasignature" not in state_code(1000, with_signature=False)
    st = parse_state("SASTATE|N|74\nSASTATE|K|2\nSASTATE|F|C:/a/auto.dta\nSAVS|make|str18|\nSAVS|foreign|byte|origin\n"
                     "SASIG|make|74:1\n")
    assert (st.n, st.k, st.names, st.signatures) == (74, 2, ["make", "foreign"], {"make": "74:1"})
    assert parse_state("nothing") is None


def test_filewatch_reports_sections():
    fw = FileWatch(DoFile.parse)
    from pathlib import Path

    p = Path("x.do")
    old = "*== [S01] a ==*\nsummarize price\n\n*== [S02] b ==*\nregress price mpg\n"
    assert fw.changes(p, old) == []  # 처음 본 파일은 기준만 기록
    new = old.replace("regress price mpg", "regress price mpg weight") + "\n*== [S03] c ==*\nsum mpg\n"
    msg = fw.changes(p, new)
    assert msg and "변경 S02" in msg[0] and "추가 S03" in msg[0]
    assert fw.changes(p, new) == []


@pytest.fixture
def svc(settings, project):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False))
    assert not s.open_session(str(project)).is_error
    return s


def test_researcher_rename_and_recode_detected_before_next_run(svc):
    svc.write_dofile("01_a.do", [{"title": "요약", "code": "summarize price"}])
    first = svc.run_section("01_a.do", "S01")
    assert "연구자 조작 감지" not in first.text  # AI 자신의 실행은 경고 없음
    # 연구자가 창에서 rename price cost, recode mpg … 를 했다고 흉내
    st = svc.backend.state
    st["vars"] = [("cost" if n == "price" else n, t, vl) for n, t, vl in st["vars"]]
    st["sig"] = {("cost" if n == "price" else n): (v + "-changed" if n == "mpg" else v) for n, v in st["sig"].items()}
    r = svc.run_section("01_a.do", "S01")
    assert "연구자 조작 감지" in r.text and "price → cost" in r.text and "값 변경 감지" in r.text and "mpg" in r.text
    assert "cost" in (svc.variables or set())  # guard가 쓰는 변수 목록도 갱신
    again = svc.run_section("01_a.do", "S01")
    assert "연구자 조작 감지" not in again.text  # 한 번 알린 뒤에는 새 기준


def test_manual_commands_from_cmdlog(svc, project):
    log = project / ".stata-agent" / "cmdlog.txt"
    log.write_text("rename price cost\nrecode mpg (12/20=1) (21/41=2)\n", encoding="utf-8")
    r = svc.check_changes()
    assert "rename price cost" in r.text and "recode mpg" in r.text and "연구자 수동 작업" in r.text
    assert "변경 없음" in svc.check_changes().text  # 읽은 줄은 다시 보고하지 않음


def test_researcher_edits_dofile_on_disk(svc, project):
    svc.write_dofile("02_b.do", [{"title": "요약", "code": "summarize price"}])
    path = project / "02_b.do"
    path.write_text(path.read_text(encoding="utf-8").replace("summarize price", "summarize price mpg"), encoding="utf-8")
    r = svc.run_section("02_b.do", "S01")
    assert "연구자 수정 감지" in r.text and "변경 S01" in r.text
    p = svc.patch_dofile("02_b.do", "add", title="추가", code="regress price mpg")
    assert "연구자 수정 감지" not in p.text and "summarize price mpg" in path.read_text(encoding="utf-8")


def test_drift_off_and_batch(settings, project, monkeypatch):
    monkeypatch.setenv("STATA_AGENT_DRIFT_CHECK", "off")
    from stata_agent.config import Settings

    off = StataAgentService(Settings.from_env(), backend=FakeBackend(), batch=FakeBackend(persistent=False))
    assert not off.open_session(str(project)).is_error
    assert not any("SASTATE" in c[1] for c in off.backend.calls if c[0] == "code")
    assert "꺼짐" in off.check_changes().text
    monkeypatch.delenv("STATA_AGENT_DRIFT_CHECK")
    batch = StataAgentService(Settings.from_env(), backend=FakeBackend(persistent=False),
                              batch=FakeBackend(persistent=False))
    assert not batch.open_session(str(project)).is_error
    assert "배치 모드" in batch.check_changes().text
