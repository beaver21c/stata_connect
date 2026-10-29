import json

import pytest

from fakes import FakeBackend
from stata_agent.service import ServiceError, StataAgentService, parse_schema


class FakeBatch(FakeBackend):
    name = "fake_batch"

    def __init__(self):
        super().__init__(persistent=False)


@pytest.fixture
def svc(settings, project):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBatch())
    assert not s.open_session(str(project)).is_error
    return s


def test_requires_session(settings):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBatch())
    with pytest.raises(ServiceError):
        s.schema()


def test_open_session_creates_convention(svc, project):
    for rel in ("00_master.do", "AGENTS.md", "CLAUDE.md", ".claude/settings.json", "output/logs", "output/tables"):
        assert (project / rel).exists(), rel
    settings_json = json.loads((project / ".claude/settings.json").read_text(encoding="utf-8"))
    assert "Read(/data/**)" in settings_json["permissions"]["deny"]
    assert svc.version_line == "version 18"


def test_load_data_returns_counts_only(svc):
    r = svc.load_data("sysuse:auto")
    assert "관측치 74개" in r.text and "Make and model" not in r.text
    assert "make" in svc.variables


def test_schema_metadata_only(svc):
    data = json.loads(svc.schema().text)
    assert data["N"] == 74 and data["K"] == 7
    rep = next(v for v in data["variables"] if v["name"] == "rep78")
    assert rep["missing"] == 5 and rep["missing_pct"] == pytest.approx(6.76)
    assert next(v for v in data["variables"] if v["name"] == "foreign")["value_label"] == "origin"


def test_write_patch_run_flow(svc, project):
    r = svc.write_dofile("04_regress.do", [{"title": "표본", "code": "sysuse auto, clear"},
                                           {"title": "모형", "code": "regress price mpg"}])
    assert not r.is_error, r.text
    assert "04_regress.do" in (project / "00_master.do").read_text(encoding="utf-8")
    r = svc.patch_dofile("04_regress.do", "add", title="강건", code="regress price mpg, vce(robust)")
    assert "S03 추가" in r.text
    assert len(list((project / ".stata-agent/backups").glob("04_regress.*.do"))) == 1
    r = svc.run_section("04_regress.do", "S03")
    assert not r.is_error and "실행 완료" in r.text
    kinds = [c[0] for c in svc.backend.calls]
    assert kinds.count("editor") == 2  # 작성·수정 후 편집기 표시(F3)
    hist = (project / ".stata-agent/history.jsonl").read_text(encoding="utf-8")
    assert "stata_run_section" in hist and "vce(robust)" not in hist  # 코드·값은 기록하지 않음


def test_blocked_section_not_executed(svc):
    svc.write_dofile("05_bad.do", [{"title": "열람", "code": "list make in 1/5"}])
    before = len(svc.backend.calls)
    r = svc.run_section("05_bad.do", "S01")
    assert r.is_error and "차단" in r.text
    assert len(svc.backend.calls) == before  # 실행 안 됨


def test_approval_flow(svc):
    svc.write_dofile("06_cd.do", [{"title": "이동", "code": "cd .."}])
    r = svc.run_section("06_cd.do", "S01")
    assert r.is_error and "acknowledge_risks" in r.text
    r = svc.run_section("06_cd.do", "S01", acknowledge_risks=True)
    assert not r.is_error


def test_identifier_probe_blocks_unique_variable(svc):
    svc.write_dofile("07_tab.do", [{"title": "빈도", "code": "tab make"}, {"title": "빈도2", "code": "tab foreign"}])
    r = svc.run_section("07_tab.do", "S01")
    assert r.is_error and "make(고유값 100%)" in r.text
    r = svc.run_section("07_tab.do", "S02")
    assert not r.is_error
    # 동의 후 실행해도 출력 필터가 단일 빈도 표를 가림
    r = svc.run_section("07_tab.do", "S01", acknowledge_risks=True)
    assert "Car01" not in r.text and "출력 필터 차단" in r.text


def test_display_of_variable_blocked_after_schema(svc):
    svc.schema()
    svc.write_dofile("08_di.do", [{"title": "값", "code": "display price"}])
    assert "G02" in svc.run_section("08_di.do", "S01").text


def test_run_dofile_and_read_log(svc, project):
    svc.write_dofile("01_describe.do", [{"title": "요약", "code": "summarize price"}])
    r = svc.run_dofile("01_describe.do")
    assert not r.is_error
    assert (project / "output/logs/01_result.log").is_file()
    assert "summarize price" in svc.read_log().text
    assert "summarize price" in svc.read_log("01_result.log").text
    assert svc.read_log("../secret.log").is_error
    pairs = json.loads(svc.read_log(fmt="dict").text.split("\n", 1)[1])
    assert any(p["command"] == "summarize price" for p in pairs)


def test_error_return_code(svc):
    svc.write_dofile("09_err.do", [{"title": "오류", "code": "summarize force_error"}])
    r = svc.run_section("09_err.do", "S01")
    assert r.is_error and "return code 111" in r.text


def test_get_results(svc):
    data = json.loads(svc.get_results(["e(r2)", "_b[weight]", "e(missing)"]).text)
    assert data["values"]["e(r2)"] == pytest.approx(0.2934)
    assert data["not_found"] == ["e(missing)"]
    assert svc.get_results(["bad name;"]).is_error


def test_export_etable(svc, project):
    r = svc.export("etable", ["m1", "m2"], "table1.docx")
    assert not r.is_error and "파일 생성" in r.text
    assert (project / "output/tables/table1.docx").is_file()
    assert svc.export("etable", ["m1"], "../x.docx").is_error


def test_reproduce_compares_logs(svc, project):
    svc.write_dofile("01_describe.do", [{"title": "요약", "code": "summarize price"}])
    svc.run_dofile("01_describe.do")
    r = svc.reproduce()
    assert "재현 확인 결과: 재현 일치" in r.text, r.text


def test_reproduce_without_interactive_logs(svc):
    r = svc.reproduce()
    assert "비교 대상 없음" in r.text


def test_path_escape_rejected(svc):
    assert svc.write_dofile("../01_x.do", [{"title": "a", "code": "b"}]).is_error
    assert svc.show_in_editor("/etc/passwd").is_error


def test_usage_summary(svc):
    svc.write_dofile("01_describe.do", [{"title": "요약", "code": "summarize price"}])
    svc.run_section("01_describe.do", "S01")
    text = svc.usage_summary("Claude Desktop").text
    assert '"runs_total": 1' in text and "AI 사용 공개문 초안" in text and "Claude Desktop" in text


def test_batch_mode_limits(settings, project):
    s = StataAgentService(settings, backend=FakeBatch(), batch=FakeBatch())
    r = s.open_session(str(project))
    assert "배치 모드" in r.text
    assert s.schema().is_error and s.get_results(["e(r2)"]).is_error


def test_parse_schema_label_with_pipe():
    text = "SASCHEMA|N|10\nSASCHEMA|K|1\nSAVAR|x|float||0|a|b\n"
    assert parse_schema(text)["variables"][0]["label"] == "a|b"
