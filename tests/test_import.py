"""기존 do-file 가져오기(IMPLEMENTATION_STATUS §14): 인코딩 변환·제목 기준 분할·행 출력 줄 주석·백업·master 등록."""

import json

import pytest

from fakes import FakeBackend
from stata_agent.dofile import DoFile, ensure_master_includes, master_entries
from stata_agent.importer import build_imported_dofile, decode_text, find_headings, outside_paths, split_points
from stata_agent.service import StataAgentService

OLD = """* 내 분석 파일
clear all
use "data/survey.dta", clear

*----------------------------------
* 1. 변수 정리
*----------------------------------
gen age2 = age^2
list id age in 1/5
foreach v of varlist inc* {
    * ---- 루프 안(분할 금지) ----
    replace `v' = . if `v' < 0
}

*----------------------------------
* 2. 회귀분석
*----------------------------------
regress y x1 x2 ///
    x3
browse
"""


@pytest.fixture
def svc(settings, project):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False))
    assert not s.open_session(str(project)).is_error
    return s


def test_decode_text_variants():
    assert decode_text("한글".encode("utf-8")) == ("한글", "utf-8")
    assert decode_text(b"\xef\xbb\xbf" + "한글".encode("utf-8")) == ("한글", "utf-8-sig")
    assert decode_text("한글".encode("cp949")) == ("한글", "cp949")


def test_headings_tiers_and_blocks():
    lines = ["**# 자료", "use x", "* ---- 장식 ----", "**# 분석", "reg y x"]
    hs = find_headings(lines)
    assert [h.title for h in hs] == ["자료", "분석"] and hs[0].kind == "bookmark"  # 책갈피가 우선
    numbered = ["* 1. 자료", "use x", "* 2) 분석", "reg y x"]
    assert [h.title for h in find_headings(numbered)] == ["1. 자료", "2) 분석"]
    blocked = ["program define p", "* ---- 안 ----", "end", "/*", "* ---- 주석 안 ----", "*/",
               "#delimit ;", "* ---- 세미콜론 ----", "#delimit cr", "reg y x ///", "* ---- 이어 쓰기 ----"]
    assert find_headings(blocked) == []
    assert split_points(["foreach v in a {", "* ---- x ----", "}"])[1] is False


def test_build_splits_and_comments_rows():
    text, meta, kind, commented, manual = build_imported_dofile(OLD, [9, 20])
    assert kind == "decorated"
    assert [(sid, title) for sid, title, _ in meta] == [("S01", "시작 부분"), ("S02", "1. 변수 정리"), ("S03", "2. 회귀분석")]
    assert [ln for ln, _ in commented] == [9, 20]
    doc = DoFile.parse(text)
    assert [s.id for s in doc.sections] == ["S01", "S02", "S03"]
    assert "* [stata-agent 가져오기" in doc.get("S02").code() and "루프 안(분할 금지)" in doc.get("S02").code()
    assert "regress y x1 x2 ///\n    x3" in doc.get("S03").code()
    # 다시 가져와도 섹션을 또 나누지 않음
    again, meta2, *_ = build_imported_dofile(text, [])
    assert meta2 == [] and again == text


def test_rows_on_brace_line_are_manual():
    src = "foreach v in a b { \n list `v' \n}\nforeach v in a { list `v' }\n"
    _, _, _, commented, manual = build_imported_dofile(src, [2, 4])
    assert [ln for ln, _ in commented] == [2] and [ln for ln, _ in manual] == [4]


def test_no_heading_wraps_all():
    _, meta, kind, _, _ = build_imported_dofile("use x\nreg y x\n", [])
    assert meta == [("S01", "기존 작업", 1)] and kind is None


def test_outside_paths(tmp_path):
    lines = ['use "D:/old/survey.dta", clear', f'use "{tmp_path.as_posix()}/data/a.dta"', "* use C:/x.dta"]
    assert [ln for ln, _ in outside_paths(lines, tmp_path)] == [1]


def test_master_keeps_imported_first():
    m = 'version 18\nclear all\ndo "분석 최종.do"\ndo "02_reg.do"\n'
    assert master_entries(m) == ["분석 최종.do", "02_reg.do"]
    out = ensure_master_includes(m, "01_desc.do", "version 18")
    assert master_entries(out) == ["분석 최종.do", "01_desc.do", "02_reg.do"]


def test_service_import_cp949_in_place(svc, project):
    path = project / "분석 최종.do"
    original = OLD.encode("cp949")
    path.write_bytes(original)
    r = svc.run_dofile("분석 최종.do")
    assert r.is_error and "stata_import_dofile" in r.text  # 친절한 안내(인코딩 오류 대신)
    prev = svc.import_dofile("분석 최종.do", preview=True)
    assert not prev.is_error and "미리보기" in prev.text and path.read_bytes() == original
    res = svc.import_dofile("분석 최종.do")
    assert not res.is_error, res.text
    assert "cp949 → UTF-8" in res.text and "S03 2. 회귀분석" in res.text and "9행: list id age in 1/5" in res.text
    new = path.read_text(encoding="utf-8")
    assert new.startswith("*== [S01] 시작 부분 ==*")
    backups = list((project / ".stata-agent" / "backups").glob("분석 최종.*.do"))
    assert backups and backups[0].read_bytes() == original  # 원본 그대로 보관
    master = (project / "00_master.do").read_text(encoding="utf-8")
    assert master_entries(master)[0] == "분석 최종.do"
    assert "프로젝트 폴더 밖" not in res.text
    # 가져온 뒤에는 실행·섹션 실행·수정이 됨
    assert not svc.run_dofile("분석 최종.do").is_error
    assert not svc.run_section("분석 최종.do", "S02").is_error
    assert not svc.patch_dofile("분석 최종.do", "add", title="추가 분석", code="summarize y").is_error
    assert "S04" in path.read_text(encoding="utf-8")
    hist = (project / ".stata-agent" / "history.jsonl").read_text(encoding="utf-8")
    rec = [json.loads(x) for x in hist.splitlines() if "stata_import_dofile" in x][-1]
    assert rec["sections"] == 3 and "list id" not in hist  # 기록에 코드 원문 없음


def test_import_rejects_master_and_missing(svc):
    assert svc.import_dofile("00_master.do").is_error
    assert svc.import_dofile("없음.do").is_error


# ── SPSS판 ────────────────────────────────────────────────────────

SPSS_OLD = """* 내 SPSS 분석.
GET FILE='data/survey.sav'.

*-----------------------------.
* 1. 변수 정리.
*-----------------------------.
RECODE age (LO THRU 29=1) (30 THRU HI=2) INTO agegrp.
LIST VARIABLES=id age
  /CASES=FROM 1 TO 5.
DO IF (sex = 1).
* ---- 블록 안(분할 금지) ----.
COMPUTE w = 1.
END IF.

*-----------------------------.
* 2. 회귀분석.
*-----------------------------.
REGRESSION /DEPENDENT y /METHOD=ENTER x1 x2.
"""


def test_spss_build_and_blocks():
    from spss_agent.importer import build_imported_syntax, find_headings
    from spss_agent.syntaxfile import SyntaxFile

    text, meta, kind, commented, manual = build_imported_syntax(SPSS_OLD, [8])
    assert kind == "decorated" and [t for _, t, _ in meta] == ["시작 부분", "1. 변수 정리", "2. 회귀분석"]
    doc = SyntaxFile.parse(text)
    s02 = doc.get("S02").code()
    assert "* [spss-agent 가져오기" in s02 and "블록 안(분할 금지)" in s02
    assert find_headings(["DO IF (x=1).", "* ---- 안 ----.", "END IF."]) == []
    # 마침표 없이 끝나는 LIST는 뒤 명령까지 주석이 되므로 손대지 않음
    _, _, _, c2, m2 = build_imported_syntax("LIST VARIABLES=id\n\nDESCRIPTIVES x.\n", [1])
    assert c2 == [] and [ln for ln, _ in m2] == [1]


def test_spss_service_import(settings, project, tmp_path):
    import shutil
    import sys
    from pathlib import Path

    from spss_agent.backend import SpssBackend
    from spss_agent.discovery import SpssInstall
    from spss_agent.engine import EngineConfig, SpssEngine
    from spss_agent.service import SpssAgentService
    from spss_agent.syntaxfile import master_entries

    home = tmp_path / "SPSS"
    shutil.copytree(Path(__file__).parent / "fake_spss_home", home)
    (home / "Python3" / "python.exe").write_text("")
    (home / "stats.exe").write_text("")

    def factory(install, work_dir, timeout):
        return SpssEngine(EngineConfig(sys.executable, install.home, work_dir, start_timeout=30, request_timeout=timeout))

    svc = SpssAgentService(settings, SpssBackend(SpssInstall(str(home), 22, "user"), 30.0, factory))
    try:
        assert not svc.open_session(str(project)).is_error
        path = project / "옛 분석.sps"
        original = SPSS_OLD.encode("cp949")
        path.write_bytes(original)
        r = svc.run_syntax_file("옛 분석.sps")
        assert r.is_error and "spss_import_syntax" in r.text
        res = svc.import_syntax("옛 분석.sps")
        assert not res.is_error and "cp949 → UTF-8" in res.text and "8행: LIST VARIABLES=id age" in res.text, res.text
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # 이 저장소 .sps 규약(UTF-8 BOM)
        backups = list((project / ".spss-agent" / "backups").glob("옛 분석.*.sps"))
        assert backups and backups[0].read_bytes() == original
        assert not (project / ".stata-agent" / "backups").exists()  # SPSS 백업 폴더 혼동 수정
        assert master_entries((project / "00_master.sps").read_text(encoding="utf-8-sig"))[0] == "옛 분석.sps"
        assert not svc.patch_syntax("옛 분석.sps", "add", title="추가", code="FREQUENCIES VARIABLES=sex.").is_error
        out = svc.run_syntax_file("옛 분석.sps")  # 규약 밖 이름도 실행·결과 파일 생성
        assert not out.is_error, out.text
        assert (project / "output" / "logs" / "옛_분석_result.txt").is_file()
    finally:
        svc.backend.close()


def test_spss_researcher_edit_detected(settings, project, tmp_path):
    import shutil
    import sys
    from pathlib import Path

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
        svc.write_syntax("01_x.sps", [{"title": "자료", "code": "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3\nEND DATA.\nEXECUTE."}])
        path = project / "01_x.sps"
        path.write_text(path.read_text(encoding="utf-8-sig").replace("1 2 3", "1 2 3 4"), encoding="utf-8-sig")
        r = svc.run_section("01_x.sps", "S01")
        assert "연구자 수정 감지" in r.text and "변경 S01" in r.text
    finally:
        svc.backend.close()
