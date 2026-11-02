"""분석·보고용 구분(IMPLEMENTATION_STATUS §20): 섹션 표지·안내 줄·가독성 참고·실행 결과 표시."""

import pytest

from fakes import FakeBackend
from stata_agent.readability import (
    ANALYSIS_NOTE,
    REPORT_NOTE,
    REPORT_TAG,
    decorate_code,
    readability_notes,
    section_title,
)
from stata_agent.service import StataAgentService

USER_EXAMPLE = """capture estimates drop r1 r2 r3
quietly regress price weight
estimates store r1
quietly regress price weight length
estimates store r2
quietly summarize price
scalar sd_y = r(sd)
matrix Bm = J(3, 4, .)
matrix Sm = J(3, 4, .)
forvalues m = 1/3 {
    quietly estimates restore r`m'
    matrix Bm[`m', 1] = _b[weight]
    matrix Fm[`m', 1] = e(r2)
}
"""


def test_notes_on_user_example():
    notes = readability_notes(USER_EXAMPLE, "analysis")
    assert any("quietly" in n and "regress price weight" in n for n in notes)
    assert any("행렬 계산 4줄" in n and "nestreg" in n for n in notes)


@pytest.mark.parametrize("code,kind,expect", [
    ("regress price weight\nestimates store r1\nnestreg: regress price (weight) (length)\n", "analysis", 0),
    ("quietly {\n    regress price weight\n}\n", "analysis", 1),
    ("qui logit foreign mpg\n", "analysis", 1),
    ("estimates restore r1\nmatrix B = e(b)\nmatrix list B\n", "report", 0),
    ("estimates restore r1\nregress price weight\n", "report", 1),
])
def test_notes_table(code, kind, expect):
    assert len(readability_notes(code, kind)) == expect


def test_title_and_note_lines():
    assert section_title("회귀 표", "report") == f"{REPORT_TAG} 회귀 표"
    assert section_title(f"{REPORT_TAG} 회귀 표", "analysis") == "회귀 표"
    assert section_title(f"{REPORT_TAG} 회귀 표", "report") == f"{REPORT_TAG} 회귀 표"  # 중복 표지 없음
    twice = decorate_code(decorate_code("regress y x", "analysis"), "report")
    assert twice.split("\n")[0] == REPORT_NOTE and ANALYSIS_NOTE not in twice and twice.count("regress y x") == 1


@pytest.fixture
def svc(settings, project):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False))
    assert not s.open_session(str(project)).is_error
    return s


def test_write_marks_sections_and_reports_notes(svc, project):
    r = svc.write_dofile("04_regress.do", [
        {"title": "단계별 회귀", "code": "quietly regress price weight\nestimates store r1"},
        {"title": "회귀 표", "kind": "report", "code": "estimates restore r1\nmatrix B = e(b)"},
    ])
    assert not r.is_error and "분석 1·보고용 1" in r.text
    assert "가독성 참고" in r.text and "S01 단계별 회귀" in r.text and "quietly" in r.text
    text = (project / "04_regress.do").read_text(encoding="utf-8")
    assert f"*== [S02] {REPORT_TAG} 회귀 표 ==*" in text
    assert ANALYSIS_NOTE in text and REPORT_NOTE in text
    run = svc.run_section("04_regress.do", "S02")
    assert run.text.startswith("※ 보고용 계산 섹션(연구자 확인 생략 가능)")
    assert "보고용 계산" not in svc.run_section("04_regress.do", "S01").text.split("\n")[0]


def test_patch_keeps_kind_on_replace(svc, project):
    svc.write_dofile("05_x.do", [{"title": "표", "kind": "report", "code": "estimates restore r1"}])
    p = svc.patch_dofile("05_x.do", "replace", section_id="S01", code="estimates restore r2\nregress price mpg")
    assert "보고용 섹션에 새 추정" in p.text
    text = (project / "05_x.do").read_text(encoding="utf-8")
    assert f"[S01] {REPORT_TAG} 표" in text and text.count(REPORT_NOTE) == 1
    add = svc.patch_dofile("05_x.do", "add", title="분석", code="regress price mpg")
    assert not add.is_error and "가독성 참고" not in add.text
    svc.patch_dofile("05_x.do", "replace", section_id="S01", kind="analysis", code="regress price weight")
    assert f"{REPORT_TAG} 표" not in (project / "05_x.do").read_text(encoding="utf-8")
