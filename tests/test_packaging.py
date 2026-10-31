"""설치·배포 경로 검사: 실행 전 검사(hook)·설치 도우미·프로젝트 .mcp.json·.mcpb manifest·플러그인·사이트 배포 정보."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import shlex
import sys
from pathlib import Path

import pytest

from stata_agent import __version__, cli, hookguard, resources, setup_wizard
from stata_agent.client_config import ServerCommand, merge_project_mcp
from stata_agent.config import Settings
from stata_agent.discovery import AboutInfo, ComRegistration, DiscoveryReport, StataInstall
from stata_agent.project import claude_settings, init_project, rendered_templates
from stata_agent.tool_specs import TOOLS

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 실행 전 검사(hook) ────────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "cat data/raw.csv",
    "Get-Content .\\data\\survey.csv",
    "type C:\\proj\\data\\x.txt",
    "python -c \"import pandas as pd; pd.read_stata('panel.dta')\"",
    "Import-Csv ./data/a.csv | Select -First 5",
    "cd data; cat raw.csv",
    "Set-Location data",
    "copy survey.sav out.sav",
])
def test_hook_blocks_raw_data(command):
    assert hookguard.check_command(command) == hookguard.REASON_DATA


@pytest.mark.parametrize("command", [
    "& 'C:\\Program Files\\Stata18\\StataSE-64.exe' /e do x.do",
    "StataMP-64 /e do 01.do",
    "stata-mp -b do x.do",
    "New-Object -ComObject stata.StataOLEApp",
])
def test_hook_blocks_direct_stata(command):
    assert hookguard.check_command(command) == hookguard.REASON_STATA


@pytest.mark.parametrize("command", [
    "ls output/tables",
    "git status",
    "Get-Content output\\logs\\01_result.log",
    "& \"$env:LOCALAPPDATA\\StataAgent\\stata-agent.exe\" doctor --json",
    "cat metadata/notes.md",
    "python make_table.py output/tables/t1.csv",
])
def test_hook_allows_normal(command):
    assert hookguard.check_command(command) is None


def test_hook_main_exit_codes():
    err = io.StringIO()
    blocked = json.dumps({"tool_name": "Bash", "tool_input": {"command": "head data/a.csv"}})
    assert hookguard.main(io.StringIO(blocked), err) == 2 and "원자료" in err.getvalue()
    other_tool = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "data/a.csv"}})
    assert hookguard.main(io.StringIO(other_tool), io.StringIO()) == 0  # Read는 권한 규칙이 담당
    assert hookguard.main(io.StringIO("not json"), io.StringIO()) == 0


# ── 설정·프로젝트 ────────────────────────────────────────────────

def test_env_placeholder_is_unset(monkeypatch):
    monkeypatch.setenv("STATA_AGENT_STATA_EXE", "${user_config.stata_exe}")
    monkeypatch.setenv("STATA_AGENT_MASK_SMALL_CELLS", "${user_config.mask_small_cells}")
    s = Settings.from_env()
    assert s.stata_exe is None and s.mask_small_cells == 0
    monkeypatch.setenv("STATA_AGENT_MASK_SMALL_CELLS", "5")
    assert Settings.from_env().mask_small_cells == 5


def test_claude_settings_hook_exec_form(tmp_path):
    s = claude_settings(["C:/x/stata-agent.exe", "hook-guard"])
    entry = s["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash|PowerShell"
    assert entry["hooks"][0] == {"type": "command", "command": "C:/x/stata-agent.exe", "args": ["hook-guard"]}
    assert "hooks" not in json.loads(rendered_templates()["claude_settings.json"])  # 템플릿은 경로 없음
    init_project(tmp_path, "version 17", hook=["exe", "hook-guard"])
    written = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["hooks"]["PreToolUse"][0]["hooks"][0]["args"] == ["hook-guard"]
    assert "Read(/data/**)" in written["permissions"]["deny"]


def test_merge_project_mcp(tmp_path):
    server = ServerCommand("${LOCALAPPDATA}/StataAgent/stata-agent.exe", ["serve"])
    c = merge_project_mcp(tmp_path, server)
    assert c.action == "created"
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["stata"] == {"command": server.command, "args": ["serve"]}
    assert merge_project_mcp(tmp_path, server).action == "unchanged"
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    c = merge_project_mcp(tmp_path, ServerCommand("y", [], {"STATA_AGENT_STATA_EXE": "C:/s.exe"}))
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert c.backup and "other" in data["mcpServers"] and data["mcpServers"]["stata"]["env"]
    (tmp_path / ".mcp.json").write_text("{broken", encoding="utf-8")
    assert merge_project_mcp(tmp_path, server).action == "error"


def test_project_command_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    exe = resources.installed_exe()
    cmd = resources.project_command(exe)
    assert cmd.command == "${LOCALAPPDATA}/StataAgent/stata-agent.exe" and cmd.args == ["serve"]
    other = resources.project_command(tmp_path / "elsewhere.exe")
    assert other.command.endswith("elsewhere.exe")


def test_skill_source_in_repo():
    assert (resources.skill_source() / "SKILL.md").is_file()


# ── 설치 도우미 ──────────────────────────────────────────────────

def _fake_report(registered=False):
    about = AboutInfo(product="Stata", edition="SE", version="17.0", perpetual=True, parsed=True,
                      serial="401706000000", licensed_to=["Secret Person", "Secret Org"])
    inst = StataInstall("C:\\Program Files\\Stata17\\StataSE-64.exe", "SE", 17, "scan", about)
    return DiscoveryReport([inst], inst, ComRegistration(registered, inst.exe if registered else None))


def test_setup_dry_run_no_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_wizard, "discover", lambda **kw: _fake_report())
    monkeypatch.setattr(setup_wizard, "IS_WINDOWS", True)
    monkeypatch.setattr(setup_wizard, "detect_clients", lambda: ["codex"])
    lines: list[str] = []
    opts = setup_wizard.SetupOptions(yes=True, dry_run=True, project=str(tmp_path / "p"))
    res = setup_wizard.run_setup(opts, ask=lambda q: "", out=lines.append)
    text = "\n".join(lines)
    assert "등록 예정" in text and "/Register" in text            # COM 등록은 계획만
    assert not (tmp_path / "p").exists()                          # 폴더 미생성
    assert "Secret" not in text and "401706" not in text          # 등록자·일련번호 미출력
    assert all(c.action in ("planned", "skipped", "unchanged") for c in res.changes)


def test_setup_project_scope_for_claude_code(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_wizard, "discover", lambda **kw: _fake_report(registered=True))
    proj = tmp_path / "proj"
    opts = setup_wizard.SetupOptions(yes=True, clients="claude-code-project", com="no", install=False,
                                     skill=False, project=str(proj), stata_exe="C:/Stata17/StataSE-64.exe")
    res = setup_wizard.run_setup(opts, out=lambda s: None)
    assert not res.errors
    mcp = json.loads((proj / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["stata"]
    assert mcp["env"]["STATA_AGENT_STATA_EXE"] == "C:/Stata17/StataSE-64.exe"
    settings = json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "hooks" in settings and (proj / "00_master.do").read_text(encoding="utf-8").count("version 17") >= 1


def test_setup_project_client_requires_project(monkeypatch):
    monkeypatch.setattr(setup_wizard, "discover", lambda **kw: _fake_report())
    opts = setup_wizard.SetupOptions(yes=True, clients="claude-code-project", com="no", install=False)
    assert setup_wizard.run_setup(opts, out=lambda s: None).errors


def test_setup_interactive_answers(monkeypatch):
    monkeypatch.setattr(setup_wizard, "discover", lambda **kw: _fake_report())
    monkeypatch.setattr(setup_wizard, "IS_WINDOWS", True)
    calls = []
    monkeypatch.setattr(setup_wizard, "register_com", lambda exe, unregister=False: (calls.append(exe), (True, "ok"))[1])
    answers = iter(["n", ""])  # COM 아니오, 마지막 Enter
    opts = setup_wizard.SetupOptions(clients="none", install=False, pause=True)
    res = setup_wizard.run_setup(opts, ask=lambda q: next(answers), out=lambda s: None)
    assert calls == [] and res.com_registered is False


def test_com_register_command_quotes():
    cmd = setup_wizard.com_register_command("C:\\O'Brien\\Stata18\\StataMP-64.exe")
    assert cmd[0] == "powershell.exe"
    assert "'C:\\O''Brien\\Stata18\\StataMP-64.exe'" in cmd[-1] and "-Verb RunAs" in cmd[-1]
    assert "/Unregister" in setup_wizard.com_register_command("x.exe", unregister=True)[-1]


def test_install_self_copies(tmp_path):
    src = tmp_path / "dl" / "stata-agent-0.1.0.exe"
    src.parent.mkdir()
    src.write_bytes(b"exe")
    dest = tmp_path / "inst" / "stata-agent.exe"
    exe, msg = setup_wizard.install_self(src=src, dest=dest)
    assert exe == dest and dest.read_bytes() == b"exe"
    exe2, msg2 = setup_wizard.install_self(src=dest, dest=dest)
    assert exe2 == dest and "이미" in msg2


# ── 명령줄 ──────────────────────────────────────────────────────

def test_default_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["stata-agent.exe"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    assert cli._default_argv(None) == ["setup", "--pause"]
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert cli._default_argv(None) == ["serve"]
    assert cli._default_argv(["doctor"]) == ["doctor"]


def test_doctor_hides_registrant(monkeypatch, capsys):
    import stata_agent.discovery as disc

    monkeypatch.setattr(disc, "discover", lambda **kw: _fake_report())
    for argv in (["doctor", "--json"], ["doctor"]):  # pytest 출력은 콘솔이 아님 → 텍스트 모드도 숨김
        with pytest.raises(SystemExit):
            cli.main(argv)
        out = capsys.readouterr().out
        assert "Secret" not in out and "401706" not in out and "StataSE-64.exe" in out


def test_plugin_setup_command_flags_exist():
    """플러그인 설치 명령(setup.md)이 쓰는 명령줄 인자가 실제로 있는지."""
    text = (ROOT / "plugins" / "stata-agent" / "commands" / "setup.md").read_text(encoding="utf-8")
    parser = cli.build_parser()
    for line in re.findall(r"^& \$(?:exe|installed) (.+)$", text, re.MULTILINE):
        line = line.replace("(Get-Location).Path", "C:/proj")
        parser.parse_args(shlex.split(line))
    assert "downloads/latest.json" in text and "--no-skill" in text


# ── .mcpb manifest ───────────────────────────────────────────────

def test_mcpb_manifest_matches_tools():
    build = _load(ROOT / "packaging" / "build.py", "pkg_build")
    m = build.manifest()
    assert m["manifest_version"] == "0.3" and m["version"] == __version__
    assert [t["name"] for t in m["tools"]] == [t.name for t in TOOLS]
    assert m["server"]["type"] == "binary" and m["server"]["entry_point"] == "server/stata-agent.exe"
    win = m["server"]["mcp_config"]["platform_overrides"]["win32"]
    assert win["command"].endswith("server/stata-agent.exe") and win["args"] == ["serve"]
    for key, value in win["env"].items():  # 사용자 설정 키가 정의돼 있고 서버가 읽는 변수임
        assert key.startswith("STATA_AGENT_")
        assert value.removeprefix("${user_config.").removesuffix("}") in m["user_config"]
    assert m["compatibility"]["platforms"] == ["win32"]


# ── 플러그인 마켓플레이스 ────────────────────────────────────────

def test_marketplace_plugins_consistent():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert market["name"] == "stata-connect"
    for entry in market["plugins"]:
        root = ROOT / entry["source"]
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        assert manifest["name"] == entry["name"] and manifest["version"] == __version__
        skills = list((root / "skills").glob("*/SKILL.md"))
        assert skills, entry["name"]
        for sk in skills:
            name = re.search(r"^name:\s*(\S+)", sk.read_text(encoding="utf-8"), re.MULTILINE).group(1)
            assert name == sk.parent.name
        assert not (root / "bin").exists()  # 최상위 bin/은 claude.ai·Cowork 설치를 막음(공식 문서)
        assert (root / "README.md").is_file()


# ── 사이트 배포 정보 ─────────────────────────────────────────────

def test_site_build_with_binaries(tmp_path):
    build = _load(ROOT / "site" / "build.py", "site_build2")
    bins = tmp_path / "bins"
    bins.mkdir()
    (bins / f"stata-agent-{__version__}.exe").write_bytes(b"MZ fake exe")
    (bins / f"stata-agent-{__version__}.mcpb").write_bytes(b"PK fake mcpb")
    (bins / "THIRD_PARTY_NOTICES.txt").write_text("notices", encoding="utf-8")
    values = build.build(tmp_path / "_site", bins)
    dl = tmp_path / "_site" / "downloads"
    latest = json.loads((dl / "latest.json").read_text(encoding="utf-8"))
    assert latest["version"] == __version__
    assert latest["exe"]["url"] == f"{build.SITE_URL}downloads/stata-agent-{__version__}.exe"
    assert latest["exe"]["sha256"] == values["EXE_SHA256"]
    sums = (dl / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert values["EXE_SHA256"] in sums and values["MCPB_SHA256"] in sums
    html = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert f'href="downloads/stata-agent-{__version__}.exe"' in html
    assert (dl / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8") == "notices"


def test_site_build_without_binaries(tmp_path):
    build = _load(ROOT / "site" / "build.py", "site_build3")
    values = build.build(tmp_path / "_site")
    assert values["EXE_SHA256"] == build.PENDING
    assert not (tmp_path / "_site" / "downloads" / "latest.json").exists()


def test_setup_command_points_to_site_latest():
    build = _load(ROOT / "site" / "build.py", "site_build4")
    text = (ROOT / "plugins" / "stata-agent" / "commands" / "setup.md").read_text(encoding="utf-8")
    assert build.SITE_URL + "downloads/latest.json" in text
