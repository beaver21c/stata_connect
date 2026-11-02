import json
import sys

import pytest

from stata_agent.client_config import (
    ServerCommand,
    install_skill,
    merge_claude_permissions,
    merge_codex_config,
    merge_desktop_config,
    remove_codex_block,
    render_codex_block,
)

SERVER = ServerCommand(r"C:\Users\me\AppData\Local\StataAgent\stata-agent-mcp.exe", [], {"STATA_AGENT_STATA_EXE": r"C:\Stata18\StataSE-64.exe"})


def test_desktop_merge_preserves_and_backs_up(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")
    ch = merge_desktop_config(cfg, SERVER)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["theme"] == "dark" and "other" in data["mcpServers"]
    assert data["mcpServers"]["stata"]["command"].endswith("stata-agent-mcp.exe")
    assert ch.action == "updated" and ch.backup
    assert merge_desktop_config(cfg, SERVER).action == "unchanged"


def test_desktop_invalid_json_untouched(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text("{broken", encoding="utf-8")
    assert merge_desktop_config(cfg, SERVER).action == "error"
    assert cfg.read_text(encoding="utf-8") == "{broken"


def test_codex_block_render_valid_toml():
    block = render_codex_block(SERVER)
    assert "command = 'C:\\Users\\me" in block  # 리터럴 문자열로 역슬래시 보존
    assert '[mcp_servers.stata.tools.stata_status]\napproval_mode = "approve"' in block
    assert "[mcp_servers.stata.tools.stata_run_section]" not in block  # 실행 도구는 기본값(prompt)
    if sys.version_info >= (3, 11):
        import tomllib

        data = tomllib.loads(block)
        assert data["mcp_servers"]["stata"]["tool_timeout_sec"] == 900.0
        assert data["mcp_servers"]["stata"]["env"]["STATA_AGENT_STATA_EXE"].startswith("C:\\Stata18")


def test_codex_merge_replaces_only_own_tables(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'model = "gpt-x"\n\n[mcp_servers.stata]\ncommand = "old"\n\n[mcp_servers.stata.env]\nA = "1"\n\n'
        '[mcp_servers.other]\ncommand = "keep"\n\n[mcp_servers."stata".tools.stata_status]\napproval_mode = "prompt"\n',
        encoding="utf-8",
    )
    ch = merge_codex_config(cfg, SERVER)
    text = cfg.read_text(encoding="utf-8")
    assert ch.action == "updated" and ch.backup
    assert 'command = "old"' not in text and 'A = "1"' not in text
    assert 'model = "gpt-x"' in text and 'command = "keep"' in text
    assert text.count("[mcp_servers.stata]") == 1
    assert merge_codex_config(cfg, SERVER).action == "unchanged"


def test_remove_block_noop():
    text, removed = remove_codex_block('[profile]\nx = 1\n')
    assert not removed and text == "[profile]\nx = 1\n"


def test_permissions_merge(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "model": "x"}), encoding="utf-8")
    merge_claude_permissions(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "Bash(ls)" in data["permissions"]["allow"]
    assert "mcp__stata__stata_status" in data["permissions"]["allow"]
    assert "mcp__stata__stata_run_section" in data["permissions"]["ask"]
    assert merge_claude_permissions(p).action == "unchanged"


def test_install_skill(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("---\nname: stata-analysis\ndescription: x\n---\n", encoding="utf-8")
    dest_root = tmp_path / "skills"
    assert install_skill(src, dest_root).action == "created"
    assert install_skill(src, dest_root).action == "unchanged"  # 재설치: 같은 내용이면 그대로(백업도 안 만듦)
    (src / "SKILL.md").write_text("---\nname: stata-analysis\ndescription: y\n---\n", encoding="utf-8")
    c = install_skill(src, dest_root)
    assert c.action == "updated" and "skills-backups" in c.backup
    assert (dest_root / "stata-analysis" / "SKILL.md").read_text(encoding="utf-8").endswith("y\n---\n")
    # 스킬 폴더 안에는 스킬 하나만(백업 사본이 중복 스킬로 잡히지 않게)
    assert [d.name for d in dest_root.iterdir()] == ["stata-analysis"]


def test_install_skill_moves_legacy_backups_out(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("x", encoding="utf-8")
    dest_root = tmp_path / "skills"
    (dest_root / "stata-analysis").mkdir(parents=True)
    (dest_root / "stata-analysis" / "SKILL.md").write_text("x", encoding="utf-8")
    legacy = dest_root / "stata-analysis.bak-20261031_120000"  # 예전 판이 스킬 폴더 안에 남긴 백업
    legacy.mkdir()
    (legacy / "SKILL.md").write_text("old", encoding="utf-8")
    c = install_skill(src, dest_root)
    assert c.action == "updated" and not legacy.exists()
    assert (tmp_path / "skills-backups" / legacy.name / "SKILL.md").is_file()


@pytest.mark.parametrize("dry", [True])
def test_dry_run_writes_nothing(tmp_path, dry):
    cfg = tmp_path / "config.toml"
    assert merge_codex_config(cfg, SERVER, dry_run=dry).action == "planned"
    assert not cfg.exists()


def test_claude_code_command_order(monkeypatch):
    """-e는 가변 인자 → 서버 이름 뒤에 와야 함(claude mcp add --help 예시 기준)."""
    from stata_agent import client_config

    monkeypatch.setattr(client_config, "find_claude_cli", lambda: "/usr/bin/claude")
    ch = client_config.register_claude_code(SERVER, dry_run=True)
    parts = ch.detail.split()
    assert parts[:8] == ["claude", "mcp", "add", "--transport", "stdio", "--scope", "user", "stata"]
    assert parts[8] == "-e" and parts.index("--") > parts.index("-e")
