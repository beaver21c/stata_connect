"""SPSS 어댑터 테스트 — 실제 SPSS 대신 tests/fake_spss_home의 가짜 spss 모듈로 엔진 서브프로세스까지 실행."""

import json
import shutil
import sys
from pathlib import Path

import anyio
import pytest

from spss_agent import server as spss_server
from spss_agent.backend import SpssBackend
from spss_agent.discovery import SpssInstall, choose, scan
from spss_agent.engine import EngineConfig, EngineError, SpssEngine
from spss_agent.guard.output_filter import filter_output
from spss_agent.guard.policy import check, split_commands
from spss_agent.project import rendered_templates
from spss_agent.selftest import EXPECTED, run_selftest
from spss_agent.service import SpssAgentService
from spss_agent.syntaxfile import (
    SyntaxFile,
    SyntaxFileError,
    ensure_master_includes,
    master_entries,
    new_syntax,
    render_master,
    validate_filename,
)
from spss_agent.tool_specs import PROFILE, TOOLS
from stata_agent.guard.command_policy import Action

FAKE_HOME = Path(__file__).parent / "fake_spss_home"
ROOT = Path(__file__).resolve().parents[1]


# ── 문법 분리·차단 규칙 ─────────────────────────────────────────
def act(code):
    return check(code, "/proj").action


def test_split_commands_periods_blank_lines_and_blocks():
    code = ("* 주석 it's ok.\nFREQUENCIES VARIABLES=a\n  /STATISTICS=MEAN.\n\nDESCRIPTIVES b\n\n"
            "BEGIN DATA\n1 2\nLIST\nEND DATA.\nBEGIN PROGRAM PYTHON3.\nimport os\nEND PROGRAM.\n"
            "COMPUTE x = 1 /* 줄 안 주석 */.\nREGRESSION /DEPENDENT y\nLIST.\n")
    cmds = [t for _, t in split_commands(code)]
    assert cmds[0].startswith("*")
    assert cmds[1].startswith("FREQUENCIES") and "/STATISTICS=MEAN" in cmds[1]
    assert "DESCRIPTIVES b" in cmds
    assert "LIST" not in cmds[:5]  # BEGIN DATA 안의 LIST는 자료
    assert any(c.startswith("BEGIN PROGRAM") for c in cmds)
    assert not any("import os" in c for c in cmds)
    assert "COMPUTE x = 1" in [c.strip() for c in cmds]
    assert cmds[-1] == "LIST"  # 마침표 없는 앞 명령 뒤 1열 위험 명령은 따로 분리


BLOCKED = [
    "LIST.", "LIS id.", "list id /CASES=FROM 1 TO 5.", "PRINT / id.", "WRITE / id.",
    "SUMMARIZE /TABLES=id score.", "HOST COMMAND=['dir'].", "ERASE FILE='x.sav'.",
    "BEGIN PROGRAM PYTHON3.\nimport spss\nEND PROGRAM.", "OMSEND.",
    "SAVE OUTFILE='C:/Users/me/x.sav'.", "SAVE OUTFILE='data/raw.sav'.",
    "SAVE TRANSLATE OUTFILE='/tmp/x.csv' /TYPE=CSV.", "WRITE OUTFILE='/tmp/x.txt' / id.",
    "MATRIX.\nGET x /FILE=*.\nPRINT x.\nEND MATRIX.",  # 자료 행렬 출력
]
ALLOWED = [
    "DESCRIPTIVES VARIABLES=score.", "REGRESSION /DEPENDENT y /METHOD=ENTER x.", "PRINT FORMATS score (F8.2).",
    "WRITE FORMATS score (F8.2).", "SUMMARIZE /TABLES=score /FORMAT=NOLIST /CELLS=MEAN.",
    "SAVE OUTFILE='output/clean.sav'.", "OMSEND TAG='mine'.", "GET FILE='data/raw.sav'.",
    "* LIST 는 주석.", "COMMENT HOST 는 주석.", "T-TEST GROUPS=g(1 2) /VARIABLES=score.",
    "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3\nEND DATA.",
]
APPROVE = [
    "CD 'C:/elsewhere'.", "REPORT /FORMAT=LIST /VARIABLES=id.", "OMS /SELECT TABLES /DESTINATION FORMAT=TEXT OUTFILE='o.txt'.",
    "SAVE TRANSLATE OUTFILE='output/x.csv' /TYPE=CSV.", "SAVE OUTFILE=myhandle.", "INSERT FILE='missing.sps'.",
    "!mymacro.", "MATRIX.\nCOMPUTE m = {1, 2}.\nEND MATRIX.",
]


@pytest.mark.parametrize("code", BLOCKED)
def test_blocked(code):
    assert act(code) == Action.BLOCK, code


@pytest.mark.parametrize("code", ALLOWED)
def test_allowed(code):
    assert act(code) <= Action.ALLOW, code


@pytest.mark.parametrize("code", APPROVE)
def test_approve(code):
    assert act(code) == Action.APPROVE, code


def test_identifier_tokens():
    r = check("FREQUENCIES VARIABLES=id sex /STATISTICS=MEAN.\nCROSSTABS /TABLES=a BY b.\n"
              "MEANS TABLES=score BY grp.\nCTABLES /TABLE region [COUNT] BY sex.\nFREQUENCIES v1 TO v5.", "/proj")
    assert r.action == Action.WARN
    assert r.identifier_vars == ["id", "sex", "a", "b", "grp", "region", "v1", "TO", "v5"]


def test_insert_recursion(tmp_path):
    (tmp_path / "02_b.sps").write_text("\ufeffLIST.\n", encoding="utf-8")
    r = check("INSERT FILE='02_b.sps'.", str(tmp_path))
    assert r.action == Action.BLOCK and r.findings[0].source == "02_b.sps"


# ── 출력 필터 ──────────────────────────────────────────────────
def test_filter_listing_and_singleton_freq():
    freq = "id\n Frequency Percent Valid Percent Cumulative Percent\n" + "\n".join(
        f"Valid A{i:03d}  1  2.0  2.0  {2.0 * (i + 1):.1f}" for i in range(12))
    text = "Descriptive Statistics\nscore 10 82.90 9.12\n\nCase Summaries\n1 72\n2 85\n\n" + freq
    r = filter_output(text)
    assert "82.90" in r.text and "A001" not in r.text and "72" not in r.text
    assert len(r.events) == 2


# ── 문법 파일 규약 ─────────────────────────────────────────────
def test_syntaxfile_roundtrip_and_edit():
    text = new_syntax("04_reg.sps", [("표본", "GET FILE='data/a.sav'."), ("모형", "REGRESSION /DEPENDENT y.")])
    assert "*== [S01] 표본 ==." in text and "계산: SPSS." in text
    doc = SyntaxFile.parse("\ufeff" + text)
    assert doc.render() == text
    doc.add("강건", "REGRESSION /DEPENDENT y /METHOD=ENTER x.", after="S01")
    assert [s.id for s in doc.sections] == ["S01", "S03", "S02"]
    with pytest.raises(SyntaxFileError):
        doc.add("x", "*== [S09] 몰래 ==.")
    with pytest.raises(SyntaxFileError):
        validate_filename("00_master.sps")


def test_master_insert_order():
    m = ensure_master_includes(render_master(["01_a.sps", "03_c.sps"]), "02_b.sps")
    assert master_entries(m) == ["01_a.sps", "02_b.sps", "03_c.sps"]
    assert "SYNTAX=INTERACTIVE ERROR=STOP." in m


# ── 탐지 ───────────────────────────────────────────────────────
def test_discovery_scan(tmp_path):
    for rel in ("IBM/SPSS Statistics/29", "IBM/SPSS Statistics/31", "IBM/SPSS/Statistics/27"):
        d = tmp_path / rel
        (d / "Python3").mkdir(parents=True)
        (d / "stats.exe").write_text("")
    (tmp_path / "IBM/SPSS Statistics/31/Python3/python.exe").write_text("")
    found = scan([str(tmp_path)])
    assert sorted(i.version for i in found) == [27, 29, 31]
    assert choose(found).version == 31  # 내장 Python 있는 최신
    assert choose(found, preferred_home=str(tmp_path / "IBM/SPSS Statistics/29")).version == 29


# ── 엔진(실제 서브프로세스 + 가짜 spss) ─────────────────────────
@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "SPSS"
    shutil.copytree(FAKE_HOME, home)
    (home / "Python3" / "python.exe").write_text("")
    (home / "stats.exe").write_text("")
    return home


def engine_factory(install, work_dir, timeout):
    return SpssEngine(EngineConfig(sys.executable, install.home, work_dir, start_timeout=30, request_timeout=timeout))


def make_backend(fake_home, timeout=30.0):
    return SpssBackend(SpssInstall(str(fake_home), 31, "user"), timeout, engine_factory)


def test_engine_protocol(fake_home, tmp_path):
    eng = SpssEngine(EngineConfig(sys.executable, str(fake_home), tmp_path / "eng", start_timeout=30, request_timeout=30))
    try:
        eng.start()
        assert eng.request("ping")["ok"]
        out = tmp_path / "o.txt"
        r = eng.request("submit", syntax="* 한글 주석.\nDATA LIST FREE / x.\nBEGIN DATA\n1 2 3 4\nEND DATA.\nDESCRIPTIVES VARIABLES=x.",
                        outfile=str(out))
        assert r["ok"] and r["err_level"] == 0 and "2.50" in out.read_text(encoding="utf-8-sig")
        d = eng.request("dictionary", missing=True)
        assert d["cases"] == 4 and d["variables"][0]["name"] == "x" and d["variables"][0]["missing"] == 0
        u = eng.request("unique", tokens=["X", "ALL"])
        assert u["counts"]["x"] == {"unique": 4, "nonmissing": 4}
        bad = eng.request("submit", syntax="FORCE_ERROR.", outfile=str(tmp_path / "e.txt"))
        assert not bad["ok"] and bad["err_level"] == 3
        assert eng.request("ping")["ok"]  # 오류 뒤에도 세션 유지
    finally:
        eng.stop()
    assert not eng.alive


def test_engine_timeout_kills_session(fake_home, tmp_path):
    eng = SpssEngine(EngineConfig(sys.executable, str(fake_home), tmp_path / "eng", start_timeout=30, request_timeout=1))
    try:
        with pytest.raises(EngineError):
            eng.request("submit", syntax="SLEEP 5", outfile=str(tmp_path / "s.txt"))
        assert not eng.alive
        assert eng.request("ping", timeout=30)["ok"]  # 다음 요청에서 재기동
    finally:
        eng.stop()


def test_engine_start_failure(tmp_path):
    eng = SpssEngine(EngineConfig(sys.executable, str(tmp_path / "no_spss"), tmp_path / "eng", start_timeout=30))
    with pytest.raises(EngineError, match="기동 실패"):
        eng.start()


# ── 서비스(엔진까지 실제 실행) ─────────────────────────────────
@pytest.fixture
def svc(settings, project, fake_home):
    s = SpssAgentService(settings, make_backend(fake_home))
    r = s.open_session(str(project))
    assert not r.is_error, r.text
    yield s
    s.backend.close()


def test_open_session_creates_convention(svc, project):
    for rel in ("00_master.sps", "AGENTS.md", ".claude/settings.json", "output/logs", ".spss-agent"):
        assert (project / rel).exists(), rel
    perms = json.loads((project / ".claude/settings.json").read_text(encoding="utf-8"))["permissions"]
    assert "mcp__spss__spss_status" in perms["allow"] and "mcp__spss__spss_run_section" in perms["ask"]


def test_write_run_read_flow(svc, project):
    r = svc.write_syntax("01_desc.sps", [
        {"title": "자료", "code": "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3 4 5 6 7 8 9 10\nEND DATA.\nCOMPUTE y = x*x.\nEXECUTE."},
        {"title": "기술통계", "code": "DESCRIPTIVES VARIABLES=x."},
    ])
    assert not r.is_error, r.text
    assert (project / "01_desc.sps").read_bytes().startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    assert "01_desc.sps" in (project / "00_master.sps").read_text(encoding="utf-8-sig")
    r = svc.run_syntax_file("01_desc.sps")
    assert not r.is_error and "5.50" in r.text, r.text
    assert (project / "output/logs/01_result.txt").is_file()
    r = svc.run_section("01_desc.sps", "S02")
    assert "5.50" in r.text
    assert "5.50" in svc.read_output().text and "5.50" in svc.read_output("01_result.txt").text
    hist = (project / ".spss-agent/history.jsonl").read_text(encoding="utf-8")
    assert "spss_run_section" in hist and "DESCRIPTIVES" not in hist


def test_blocked_and_approval(svc):
    svc.write_syntax("02_bad.sps", [{"title": "목록", "code": "LIST."}, {"title": "이동", "code": "CD 'C:/x'."}])
    before = svc.backend.engine.request("ping")  # 엔진 정상
    assert before["ok"]
    r = svc.run_section("02_bad.sps", "S01")
    assert r.is_error and "S01" in r.text and "차단" in r.text
    r = svc.run_section("02_bad.sps", "S02")
    assert r.is_error and "acknowledge_risks" in r.text


def test_identifier_check_and_filter(svc, project):
    (project / "data" / "a.sav").write_bytes(b"$FL2")
    assert "사례 3개" in svc.load_data("data/a.sav").text
    svc.write_syntax("03_freq.sps", [{"title": "빈도", "code": "FREQUENCIES VARIABLES=id."}])
    r = svc.run_section("03_freq.sps", "S01")
    assert r.is_error and "id(고유값 100%)" in r.text
    schema = json.loads(svc.schema().text)
    age = next(v for v in schema["variables"] if v["name"] == "age")
    assert schema["cases"] == 3 and age["missing"] == 1 and age["missing_pct"] == pytest.approx(33.33)


def test_export_and_reproduce(svc, project):
    svc.write_syntax("01_desc.sps", [
        {"title": "자료", "code": "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3 4\nEND DATA.\nCOMPUTE y = x*x.\nEXECUTE."},
        {"title": "상관", "code": "CORRELATIONS /VARIABLES=x y."},
    ])
    svc.run_section("01_desc.sps", "S01")
    r = svc.export("01_desc.sps", "S02", "table1.docx")
    assert not r.is_error and (project / "output/tables/table1.docx").is_file(), r.text
    svc.run_syntax_file("01_desc.sps")
    r = svc.reproduce()
    assert "재현 확인 결과: 재현 일치" in r.text, r.text
    assert "SPSS" in svc.usage_summary("Codex").text


def test_selftest_with_fake_engine(settings, fake_home):
    svc = SpssAgentService(settings, make_backend(fake_home))
    results, meta = run_selftest(svc, "Claude Desktop", release_lookup=lambda: "v0.1.0")
    status = {r.id: r.status for r in results}
    assert all(v == "pass" for v in status.values()), [(r.id, r.status, r.detail) for r in results]
    assert meta["software"] == "SPSS" and EXPECTED["r"] == pytest.approx(0.97460, abs=1e-4)


def test_unavailable_without_install(settings, project):
    s = SpssAgentService(settings, SpssBackend(None))
    assert "설치를 찾지 못함" in s.open_session(str(project)).text


# ── 서버·스킬·템플릿 ───────────────────────────────────────────
def test_tool_list_and_profile():
    names = {t.name for t in spss_server.list_tool_objects()}
    assert names == {t.name for t in TOOLS} and len(names) == 13
    assert PROFILE.server_name == "spss" and "spss_schema" in PROFILE.read_only_tools


def test_in_memory_roundtrip(settings, project, fake_home, monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session

    svc = SpssAgentService(settings, make_backend(fake_home))
    monkeypatch.setattr(spss_server, "_service", svc)

    async def run():
        async with create_connected_server_and_client_session(spss_server.server) as client:
            assert len((await client.list_tools()).tools) == 13
            r = await client.call_tool("spss_open_session", {"project_dir": str(project)})
            assert "SPSS 세션 준비" in r.content[0].text
            r = await client.call_tool("spss_run_section", {"filename": "01_x.sps", "section_id": "S01"})
            assert r.content[0].text.startswith("[오류]")

    try:
        anyio.run(run)
    finally:
        svc.backend.close()


def test_skill_and_templates():
    skill = ROOT / "skills" / "spss-analysis"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: spss-analysis\ndescription: ")
    desc = text.split("description: ", 1)[1].split("\n", 1)[0]
    assert len(desc) <= 1024
    for t in TOOLS:
        assert t.name in text, t.name
    for name, content in rendered_templates().items():
        assert (skill / "templates" / name).read_text(encoding="utf-8-sig") == content, name
    assert act((skill / "templates" / "01_describe.sps").read_text(encoding="utf-8-sig")) <= Action.WARN
