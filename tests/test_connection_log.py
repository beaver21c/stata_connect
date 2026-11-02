"""연결 진단(IMPLEMENTATION_STATUS §19): 도구 쪽 시작 기록·Claude 앱 기록 판독·설치 화면 저장."""

import json
import os
import sys

from stata_agent import connection_log as cl
from stata_agent import setup_wizard


def test_record_keeps_last_50_and_never_raises(tmp_path):
    for i in range(60):
        cl.record(tmp_path, "list_tools", client=f"c{i}")
    recs = cl.read_records(tmp_path)
    assert len(recs) == 50 and recs[-1]["client"] == "c59" and "pid" in recs[-1]
    blocker = tmp_path / "file"
    blocker.write_text("x")
    cl.record(blocker / "sub", "start")  # 폴더를 만들 수 없어도 예외 없음


def _cfg(tmp_path):
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    (cfg.parent / "logs").mkdir(parents=True)
    return cfg


def test_report_no_trace(tmp_path):
    cfg = _cfg(tmp_path)
    lines = cl.connection_report("stata", "Stata", tmp_path / "inst", [cfg])
    assert "연결된 기록 없음" in lines[0] and "시작 흔적 없음" in lines[1]


def test_report_reads_claude_logs(tmp_path):
    cfg = _cfg(tmp_path)
    (cfg.parent / "logs" / "mcp-server-stata.log").write_text(
        "2026-11-02 info Initializing server\n2026-11-02 error spawn C:\\x\\stata-agent.exe ENOENT\n", encoding="utf-8")
    cl.record(tmp_path / "inst", "list_tools", client="claude-ai 0.1.0")
    lines = cl.connection_report("stata", "Stata", tmp_path / "inst", [cfg])
    assert "claude-ai 0.1.0" in lines[0] and "시작한 기록 있음" in lines[1] and "ENOENT" in lines[2]


def test_report_shared_log_mention_counts(tmp_path):
    cfg = _cfg(tmp_path)
    (cfg.parent / "logs" / "mcp.log").write_text("x [stata] Server transport closed unexpectedly, error\nother\n",
                                                encoding="utf-8")
    lines = cl.connection_report("stata", "Stata", tmp_path / "inst", [cfg])
    assert "시작한 기록 있음" in lines[1] and "transport closed" in lines[2]


def test_server_records_client_on_list_tools(settings, project, monkeypatch):
    import anyio
    import pytest

    try:
        from mcp.shared.memory import create_connected_server_and_client_session
    except ImportError:
        pytest.skip("mcp 메모리 전송 미지원 버전")
    from fakes import FakeBackend
    from stata_agent import server as srv
    from stata_agent.service import StataAgentService

    monkeypatch.setattr(srv, "_service", StataAgentService(settings, backend=FakeBackend(),
                                                           batch=FakeBackend(persistent=False)))
    monkeypatch.setattr(srv, "_connected_noted", False)

    async def run():
        async with create_connected_server_and_client_session(srv.server) as client:
            await client.list_tools()

    anyio.run(run)
    recs = cl.read_records(srv._APP.install_dir())
    assert recs and recs[-1]["event"] == "list_tools" and recs[-1].get("client")


def test_wizard_shows_diagnosis_and_saves_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    pkg = os.path.join(os.environ["LOCALAPPDATA"], "Packages", "Claude_pzs8sxrjxfjjc")
    os.makedirs(os.path.join(pkg, "LocalCache", "Roaming", "Claude", "logs"))
    from test_packaging import _fake_report

    monkeypatch.setattr(setup_wizard, "discover", lambda **kw: _fake_report(registered=True))
    monkeypatch.setattr(setup_wizard.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup_wizard, "codex_home", lambda: tmp_path / "nocodex")
    lines: list[str] = []
    res = setup_wizard.run_setup(setup_wizard.SetupOptions(yes=True, com="no", install=False, skill=False),
                                 out=lines.append)
    text = "\n".join(lines)
    assert not res.errors, text
    assert "연결 진단" in text and "시작 흔적 없음" in text
    saved = setup_wizard.STATA.install_dir() / "setup_last.txt"
    assert saved.is_file() and "연결 진단" in saved.read_text(encoding="utf-8") and str(saved) in text
    assert "Secret" not in saved.read_text(encoding="utf-8")  # 등록자 등은 화면에도 파일에도 없음
