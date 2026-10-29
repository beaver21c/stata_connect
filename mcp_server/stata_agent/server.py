"""MCP 진입점(stdio). 도구 목록은 tool_specs.TOOLS, 동작은 service.StataAgentService.

상류 stata-gui-mcp의 도구 목록은 노출하지 않음(래퍼: 세션·실행 기능만 내부 사용).
"""

from __future__ import annotations

import asyncio
import functools

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, ToolAnnotations

from . import __version__
from .selftest import results_table, run_selftest, to_dicts
from .report import save_report
from .service import ServiceError, StataAgentService, ToolResult
from .tool_specs import SERVER_NAME, TOOLS

server = Server(SERVER_NAME, version=__version__)
_service: StataAgentService | None = None


def get_service() -> StataAgentService:
    global _service
    if _service is None:
        _service = StataAgentService()
    return _service


def list_tool_objects() -> list[Tool]:
    return [
        Tool(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema(),
            annotations=ToolAnnotations(
                readOnlyHint=t.read_only,
                destructiveHint=False,
                openWorldHint=t.name == "stata_install_package",
            ),
        )
        for t in TOOLS
    ]


def dispatch(service: StataAgentService, name: str, args: dict) -> ToolResult:
    a = args or {}
    if name == "stata_status":
        return service.status(bool(a.get("refresh")))
    if name == "stata_selftest":
        child = service.child_for_selftest()
        results, meta = run_selftest(child, a.get("client_name"), a.get("include_batch", True))
        path = save_report(results, meta, service.settings.report_dir)
        return ToolResult(f"{results_table(results)}\n\n점검 보고서: {path}\n(오류 보고 시 이 파일만 첨부)")
    if name == "stata_open_session":
        return service.open_session(a["project_dir"], a.get("session_id"))
    if name == "stata_load_data":
        return service.load_data(a["path"])
    if name == "stata_schema":
        return service.schema()
    if name == "stata_write_dofile":
        return service.write_dofile(a["filename"], a.get("sections") or [], a.get("author"), bool(a.get("overwrite")))
    if name == "stata_patch_dofile":
        return service.patch_dofile(a["filename"], a["action"], a.get("section_id"), a.get("title"),
                                    a.get("code"), a.get("after"))
    if name == "stata_show_in_editor":
        return service.show_in_editor(a["filename"])
    if name == "stata_run_section":
        return service.run_section(a["filename"], a["section_id"], bool(a.get("acknowledge_risks")))
    if name == "stata_run_dofile":
        return service.run_dofile(a["filename"], bool(a.get("acknowledge_risks")))
    if name == "stata_read_log":
        return service.read_log(a.get("name"), a.get("tail_lines"), a.get("format") or "text")
    if name == "stata_get_results":
        return service.get_results(a.get("names"), a.get("kind"))
    if name == "stata_export":
        return service.export(a["mode"], a.get("estimates"), a.get("filename"), a.get("code"),
                              bool(a.get("acknowledge_risks")))
    if name == "stata_reproduce":
        return service.reproduce(a.get("master"))
    if name == "stata_break":
        return service.break_execution()
    if name == "stata_install_package":
        return service.install_package(a["package"], a.get("source") or "ssc", a.get("from_url"))
    if name == "stata_usage_summary":
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
    except Exception as e:  # 도구 오류는 대화로 전달
        result = ToolResult(f"도구 실행 오류({type(e).__name__}): {e}", True)
    prefix = "[오류] " if result.is_error else ""
    return [TextContent(type="text", text=prefix + result.text)]


async def serve() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
