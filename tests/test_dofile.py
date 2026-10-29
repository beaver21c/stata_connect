import pytest

from stata_agent.dofile import (
    DoFile,
    DoFileError,
    ensure_master_includes,
    master_entries,
    new_dofile,
    render_master,
    section_run_code,
    validate_filename,
)


def make():
    return new_dofile("04_regress.do", [("표본 정의", "sysuse auto, clear"), ("기본 모형", "regress price mpg")], "version 19")


def test_new_dofile_follows_convention():
    text = make()
    assert "* 04_regress.do | 작성: AI / 승인: 연구자 / 계산: Stata" in text
    assert 'log using "output/logs/04_result.log", text replace name(_nmlog)' in text
    assert "*== [S01] 표본 정의 ==*" in text and "*== [S02] 기본 모형 ==*" in text
    assert text.rstrip().endswith("log close _nmlog")


def test_roundtrip_stable():
    text = make()
    assert DoFile.parse(text).render() == text


def test_add_replace_delete_keeps_footer_last():
    doc = DoFile.parse(make())
    doc.add("이분산 점검", "estat hettest")
    doc.add("강건 표준오차", "regress price mpg, vce(robust)", after="S02")
    assert [s.id for s in doc.sections] == ["S01", "S02", "S04", "S03"]
    doc.replace("S02", "regress price mpg weight", title="기본 모형(수정)")
    doc.delete("S01")
    out = doc.render()
    assert out.rstrip().endswith("log close _nmlog")
    assert "regress price mpg weight" in out and "sysuse auto" not in out
    assert "*== [S02] 기본 모형(수정) ==*" in out


def test_section_code_rules():
    doc = DoFile.parse(make())
    with pytest.raises(DoFileError):
        doc.add("x", "*== [S09] 몰래 ==*\nlist")
    with pytest.raises(DoFileError):
        doc.add("x", "log close _nmlog")
    with pytest.raises(DoFileError):
        doc.get("S99")
    with pytest.raises(DoFileError):
        doc.add("dup", "x", section_id="S01")


def test_section_run_code_includes_version():
    code = section_run_code(DoFile.parse(make()), "2")
    assert code.startswith("version 19\n")
    assert "regress price mpg" in code and "sysuse" not in code


def test_filename_rules():
    validate_filename("01_describe.do")
    for bad in ("describe.do", "1_x.do", "00_master.do", "01_x.txt", "../01_x.do"):
        with pytest.raises(DoFileError):
            validate_filename(bad)


def test_master_includes_sorted():
    m = render_master(["01_describe.do", "03_corr.do"], "version 18")
    m = ensure_master_includes(m, "02_compare.do", "version 18")
    m = ensure_master_includes(m, "02_compare.do", "version 18")  # 중복 추가 없음
    assert master_entries(m) == ["01_describe.do", "02_compare.do", "03_corr.do"]
    assert master_entries(ensure_master_includes(None, "05_x.do", "version 18")) == ["05_x.do"]
