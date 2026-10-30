"""SPSS MCP 진입점(stdio, 서버 이름 spss)."""

from __future__ import annotations

import asyncio
import functools

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, ToolAnnotations

from stata_agent.report import save_report
from stata_agent.selftest import results_table
from stata_agent.service import ServiceError, ToolResult

from . import __version__
from .selftest import run_selftest
from .service import SpssAgentService
from .tool_specs import SERVER_NAME, TOOLS

server = Server(SERVER_NAME, version=__version__)
_service: SpssAgentService | None = None


def get_service() -> SpssAgentService:
    global _service
    if _service is None:
        _service = SpssAgentService()
    return _service


def list_tool_objects() -> list[Tool]:
    return [
        Tool(name=t.name, description=t.description, inputSchema=t.input_schema(),
             annotations=ToolAnnotations(readOnlyHint=t.read_only, destructiveHint=False, openWorldHint=False))
        for t in TOOLS
    ]


def dispatch(service: SpssAgentService, name: str, args: dict) -> ToolResult:
    a = args or {}
    if name == "spss_status":
        return service.status(bool(a.get("refresh")))
    if name == "spss_selftest":
        results, meta = run_selftest(service.child_for_selftest(), a.get("client_name"), a.get("include_batch", True))
        path = save_report(results, meta, service.settings.report_dir)
        return ToolResult(f"{results_table(results)}\n\n점검 보고서: {path}\n(오류 보고 시 이 파일만 첨부)")
    if name == "spss_open_session":
        return service.open_session(a["project_dir"])
    if name == "spss_load_data":
        return service.load_data(a["path"])
    if name == "spss_schema":
        return service.schema()
    if name == "spss_write_syntax":
        return service.write_syntax(a["filename"], a.get("sections") or [], a.get("author"), bool(a.get("overwrite")))
    if name == "spss_patch_syntax":
        return service.patch_syntax(a["filename"], a["action"], a.get("section_id"), a.get("title"),
                                    a.get("code"), a.get("after"))
    if name == "spss_run_section":
        return service.run_section(a["filename"], a["section_id"], bool(a.get("acknowledge_risks")))
    if name == "spss_run_syntax_file":
        return service.run_syntax_file(a["filename"], bool(a.get("acknowledge_risks")))
    if name == "spss_read_output":
        return service.read_output(a.get("name"), a.get("tail_lines"))
    if name == "spss_export":
        return service.export(a["filename"], a["section_id"], a["output"], bool(a.get("acknowledge_risks")))
    if name == "spss_reproduce":
        return service.reproduce()
    if name == "spss_usage_summary":
        return service.usage_summary(a.get("client_name"))
    return ToolResult(f"알 수 없는 도구: {name}", True)


@server.list_tools()
async def _list_tools() -> list[Tool]:
    return list_tool_objects()


@server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, functools.partial(dispatch, get_service(), name, arguments))
    except ServiceError as e:
        result = ToolResult(str(e), True)
    except KeyError as e:
        result = ToolResult(f"필수 인자 누락: {e}", True)
    except Exception as e:
        result = ToolResult(f"도구 실행 오류({type(e).__name__}): {e}", True)
    return [TextContent(type="text", text=("[오류] " if result.is_error else "") + result.text)]


async def serve() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
