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
