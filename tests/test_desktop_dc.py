"""Claude 앱 직접 등록(일반판·스토어판 위치)·Desktop Commander 차단 목록(IMPLEMENTATION_STATUS §17).

conftest의 자동 격리로 APPDATA·LOCALAPPDATA·Desktop Commander 설정은 모두 임시 폴더를 가리킴.
"""

import json
import ntpath
import os
import sys
import time

import pytest

from stata_agent import client_config as cc
from stata_agent import dc_guard
from stata_agent import setup_wizard
from stata_agent.client_config import ServerCommand, backup, claude_desktop_config_paths, configure_all

SERVER = ServerCommand("C:/Users/u/AppData/Local/StataAgent/stata-agent.exe", ["serve"])


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    local, roaming = os.environ["LOCALAPPDATA"], os.environ["APPDATA"]
    return local, roaming


def _store_pkg(local):
    pkg = os.path.join(local, "Packages", "Claude_pzs8sxrjxfjjc")
    os.makedirs(pkg)
    return pkg


def test_paths_store_and_standard(win):
    local, roaming = win
    assert claude_desktop_config_paths() == []  # 앱 없음
    _store_pkg(local)
    os.makedirs(os.path.join(roaming, "Claude"))
    kinds = [(k, p.name) for k, p in claude_desktop_config_paths()]
    assert kinds == [("store", "claude_desktop_config.json"), ("standard", "claude_desktop_config.json")]
    store = claude_desktop_config_paths()[0][1]
    assert store.parts[-4:] == ("LocalCache", "Roaming", "Claude", "claude_desktop_config.json")


def test_configure_desktop_writes_store_location_and_keeps_others(win):
    local, _ = win
    pkg = _store_pkg(local)
    cfg_dir = os.path.join(pkg, "LocalCache", "Roaming", "Claude")
    os.makedirs(cfg_dir)
    cfg = os.path.join(cfg_dir, "claude_desktop_config.json")
    # 메모장 저장(BOM) + 다른 서버·설정 유지 확인
    with open(cfg, "w", encoding="utf-8-sig") as f:
        json.dump({"mcpServers": {"other": {"command": "x"}}, "preferences": {"a": 1}}, f)
    changes = configure_all(SERVER, cc.Path("."), ["claude-desktop"], install_skills=False)
    assert [c.action for c in changes] == ["updated"] and changes[0].backup
    raw = open(cfg, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")  # BOM 없이 기록(JSON.parse 호환)
    data = json.loads(raw.decode("utf-8"))
    assert data["mcpServers"]["other"] == {"command": "x"} and data["preferences"] == {"a": 1}
    assert data["mcpServers"]["stata"] == {"command": SERVER.command, "args": ["serve"]}
    assert configure_all(SERVER, cc.Path("."), ["claude-desktop"], install_skills=False)[0].action == "unchanged"


def test_configure_desktop_creates_store_file_when_missing(win):
    local, _ = win
    _store_pkg(local)  # 앱이 아직 설정 파일을 만들지 않은 상태
    c = configure_all(SERVER, cc.Path("."), ["claude-desktop"], install_skills=False)
    assert c[0].action == "created"
    path = claude_desktop_config_paths()[0][1]
    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["stata"]["args"] == ["serve"]


def test_configure_desktop_not_found(win):
    c = configure_all(SERVER, cc.Path("."), ["claude-desktop"], install_skills=False)
    assert c[0].action == "skipped" and "찾지 못함" in c[0].detail


def test_backup_names_never_collide(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("1")
    first = backup(p)
    p.write_text("2")
    second = backup(p)
    assert first != second and open(first).read() == "1" and open(second).read() == "2"


def test_wizard_registers_claude_app_in_plain_words(win, monkeypatch):
    local, _ = win
    _store_pkg(local)
    from test_packaging import _fake_report

    monkeypatch.setattr(setup_wizard, "discover", lambda **kw: _fake_report(registered=True))
    monkeypatch.setattr(setup_wizard.shutil, "which", lambda name: None)  # Claude Code·Codex 없음
    monkeypatch.setattr(setup_wizard, "codex_home", lambda: cc.Path(local) / "nocodex")
    lines: list[str] = []
    res = setup_wizard.run_setup(setup_wizard.SetupOptions(yes=True, com="no", install=False, skill=False),
                                 out=lines.append)
    text = "\n".join(lines)
    assert not res.errors, text
    assert "Claude 앱(Microsoft Store판): 등록 완료" in text and ".mcpb" not in text
    assert "Stata 연결 점검해줘" in text and "[6/6] 원자료 보호" in text


# ── Desktop Commander ───────────────────────────────────────────

DEFAULTS = ["mkfs", "format", "reg", "net", "sc", "runas", "cipher", "takeown"]


def _dc(tmp_path, data):
    p = dc_guard.dc_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def test_dc_names_match_dc_rule():
    # Desktop Commander 규칙: 첫 낱말의 파일 이름(path.basename)을 소문자로 바꿔 목록과 정확히 비교 [1차 확인: 소스]
    for cmd in (r"C:\Stata17\StataSE-64.exe", r"C:\Stata18\StataMP-64", "StataBE-64.exe", "/usr/local/stata18/stata-mp"):
        base = ntpath.basename(cmd) if "\\" in cmd else cmd.rsplit("/", 1)[-1]
        assert base.lower() in dc_guard.STATA_COMMANDS, cmd
    for cmd in (r"C:\Program Files\IBM\SPSS\Statistics\27\stats.exe", "statisticsb", "runsyntx.exe"):
        assert ntpath.basename(cmd).lower() in dc_guard.SPSS_COMMANDS
    assert all(c == c.lower() for c in dc_guard.STATA_COMMANDS + dc_guard.SPSS_COMMANDS)


def test_dc_add_keeps_existing_and_other_keys(tmp_path):
    p = _dc(tmp_path, {"blockedCommands": DEFAULTS, "defaultShell": "powershell", "allowedDirectories": []})
    c = dc_guard.add_blocked_commands(dc_guard.STATA_COMMANDS)
    assert c.action == "updated" and c.backup
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["blockedCommands"][: len(DEFAULTS)] == DEFAULTS and "statase-64.exe" in data["blockedCommands"]
    assert data["defaultShell"] == "powershell" and data["allowedDirectories"] == []
    assert dc_guard.add_blocked_commands(dc_guard.STATA_COMMANDS).action == "unchanged"
    both = dc_guard.add_blocked_commands(dc_guard.SPSS_COMMANDS)
    assert both.action == "updated" and "stats.exe" in json.loads(p.read_text(encoding="utf-8"))["blockedCommands"]


def test_dc_skip_error_and_lock(tmp_path):
    assert dc_guard.add_blocked_commands(dc_guard.STATA_COMMANDS).action == "skipped"  # 미사용
    p = _dc(tmp_path, {"blockedCommands": DEFAULTS})
    p.write_text("{broken", encoding="utf-8")
    bad = dc_guard.add_blocked_commands(dc_guard.STATA_COMMANDS)
    assert bad.action == "error" and p.read_text(encoding="utf-8") == "{broken"  # 손대지 않음
    p = _dc(tmp_path, {"blockedCommands": DEFAULTS})
    lock = p.with_name("config.json.lock")
    lock.mkdir()
    locked = dc_guard.add_blocked_commands(dc_guard.STATA_COMMANDS, wait_seconds=0)
    assert locked.action == "error" and "statase-64.exe" not in p.read_text(encoding="utf-8")
    old = time.time() - 120
    os.utime(lock, (old, old))  # 오래된 잠금(비정상 종료 흔적)은 무시
    assert dc_guard.add_blocked_commands(dc_guard.STATA_COMMANDS, wait_seconds=0).action == "updated"


def test_dc_dry_run_and_wizard_step(tmp_path):
    p = _dc(tmp_path, {"blockedCommands": DEFAULTS})
    before = p.read_text(encoding="utf-8")
    assert dc_guard.add_blocked_commands(dc_guard.STATA_COMMANDS, dry_run=True).action == "planned"
    assert p.read_text(encoding="utf-8") == before
    lines: list[str] = []
    opts = setup_wizard.SetupOptions(yes=True)
    errs = setup_wizard.protect_desktop_commander(dc_guard.STATA_COMMANDS, "Stata", opts, input, lines.append)
    assert not errs and any("차단 추가 완료" in x for x in lines) and any("끈 상태로" in x for x in lines)


def test_server_instructions_forbid_shell_route():
    from spss_agent import server as spss_srv
    from stata_agent import server as srv

    for s, prod in ((srv, "Stata"), (spss_srv, "SPSS")):
        text = s.server.instructions or ""
        assert prod in text and "Desktop Commander" in text and "data" in text
