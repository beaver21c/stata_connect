import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    return root


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("STATA_AGENT_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STATA_AGENT_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("STATA_AGENT_STATA_VERSION", "18")
    from stata_agent.config import Settings

    return Settings.from_env()


@pytest.fixture(autouse=True)
def _isolate_user_settings(tmp_path, monkeypatch):
    """테스트가 실제 사용자 설정(Claude 앱·Desktop Commander)을 건드리지 않게 위치를 임시 폴더로 바꿈.
    (2026-11-02: 설치 도우미 테스트가 개발 환경의 Desktop Commander 설정을 고친 사고 재발 방지)"""
    import stata_agent.client_config as cc
    import stata_agent.dc_guard as dc
    import stata_agent.setup_wizard as sw

    home = tmp_path / "_user"
    monkeypatch.setattr(dc, "dc_config_path", lambda: home / ".claude-server-commander" / "config.json")
    # 개발 환경의 실제 claude 명령으로 사용자 범위 등록을 하지 않게 함(필요한 테스트는 다시 덮어씀)
    monkeypatch.setattr(cc, "find_claude_cli", lambda: None)
    monkeypatch.setattr(sw, "find_claude_cli", lambda: None)
    monkeypatch.setattr(cc, "claude_user_config_path", lambda: home / ".claude.json", raising=False)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))

