"""MCP 서버 연결부: 도구 목록·주석·디스패치, 메모리 내 클라이언트 왕복."""

import anyio
import pytest

from fakes import FakeBackend
from stata_agent import server as srv
from stata_agent.service import StataAgentService
from stata_agent.tool_specs import READ_ONLY_TOOLS, TOOLS

DESIGN_TOOLS = {  # 설계서 §7 표
    "stata_status", "stata_selftest", "stata_open_session", "stata_load_data", "stata_schema",
    "stata_write_dofile", "stata_patch_dofile", "stata_show_in_editor", "stata_run_section",
    "stata_run_dofile", "stata_read_log", "stata_get_results", "stata_export", "stata_reproduce",
    "stata_break", "stata_install_package",
}


def test_tool_list_covers_design():
    names = {t.name for t in srv.list_tool_objects()}
    assert DESIGN_TOOLS <= names
    assert names - DESIGN_TOOLS == {"stata_usage_summary"}


def test_permission_classes_match_design():
    assert set(READ_ONLY_TOOLS) == {
        "stata_status", "stata_selftest", "stata_schema", "stata_show_in_editor", "stata_read_log",
        "stata_get_results", "stata_break", "stata_usage_summary",
    }
    for t in srv.list_tool_objects():
        spec = next(s for s in TOOLS if s.name == t.name)
        assert t.annotations.readOnlyHint == spec.read_only


def test_dispatch_unknown(settings):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False))
    assert srv.dispatch(s, "nope", {}).is_error


def test_in_memory_roundtrip(settings, project, monkeypatch):
    try:
        from mcp.shared.memory import create_connected_server_and_client_session
    except ImportError:
        pytest.skip("mcp 메모리 전송 미지원 버전")
    svc = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False))
    monkeypatch.setattr(srv, "_service", svc)

    async def run():
        async with create_connected_server_and_client_session(srv.server) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == len(TOOLS)
            r = await client.call_tool("stata_open_session", {"project_dir": str(project)})
            assert "세션 준비" in r.content[0].text
            r = await client.call_tool("stata_load_data", {"path": "sysuse:auto"})
            assert "관측치 74개" in r.content[0].text
            r = await client.call_tool("stata_run_section", {"filename": "01_x.do", "section_id": "S01"})
            assert r.content[0].text.startswith("[오류]")

    anyio.run(run)
