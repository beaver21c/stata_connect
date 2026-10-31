"""빌드한 실행파일 점검(Stata 없이) — CI windows 작업에서 실행.

1. --version 일치
2. doctor --json: 등록자·일련번호 항목 없음
3. MCP 서버: ``serve``와 인자 없음(입력 연결) 두 방식으로 초기화 + 도구 목록 = tool_specs
4. hook-guard: 원자료 명령 차단(종료 코드 2), 일반 명령 통과(0)
5. setup --dry-run: 질문 없이 끝까지 진행
6. 묶은 스킬: configure --dry-run에서 스킬 원본 오류 없음
7. (선택) .mcpb: manifest.json·server/stata-agent.exe 포함, 도구 목록 일치

사용: python packaging/smoke_test.py <실행파일> [--mcpb <파일>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))

from stata_agent import __version__  # noqa: E402
from stata_agent.tool_specs import TOOLS  # noqa: E402

EXPECTED = sorted(t.name for t in TOOLS)


def run(exe: str, *args: str, stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run([exe, *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, check=False)


async def list_tools(exe: str, args: list[str]) -> list[str]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=exe, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return sorted(t.name for t in tools.tools)


def check(cond: bool, label: str, detail: str = "") -> bool:
    print(("통과 " if cond else "실패 ") + label + (f" — {detail}" if detail and not cond else ""))
    return cond


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows CI 파이프 출력(cp1252)에서 한글 오류 방지
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--mcpb")
    args = ap.parse_args()
    exe = str(Path(args.exe).resolve())
    ok = True

    r = run(exe, "--version")
    ok &= check(r.stdout.strip() == __version__, "버전", r.stdout + r.stderr)

    r = run(exe, "doctor", "--json", "--no-about")
    try:
        text = r.stdout
        data = json.loads(text)
        ok &= check("installs" in data and "licensed_to" not in text and "serial" not in text,
                    "doctor --json(등록자·일련번호 없음)", text[:300])
        layer = data.get("com_layer") or {}
        # 상류 모듈·배포 정보(--copy-metadata) 묶음 확인, Windows는 pywin32까지
        need_pywin32 = sys.platform.startswith("win")
        ok &= check(layer.get("upstream") is True and (layer.get("pywin32") is True or not need_pywin32),
                    "화면 연동 계층 포함(stata-gui-mcp" + ("·pywin32)" if need_pywin32 else ")"), json.dumps(layer, ensure_ascii=False))
    except ValueError:
        ok &= check(False, "doctor --json", r.stdout[:300] + r.stderr[:300])

    for label, a in (("MCP serve", ["serve"]), ("MCP 인자 없음", [])):
        try:
            names = asyncio.run(asyncio.wait_for(list_tools(exe, a), 120))
            ok &= check(names == EXPECTED, label, f"{names}")
        except Exception as e:  # noqa: BLE001 — 점검 보고용
            ok &= check(False, label, repr(e))

    blocked = json.dumps({"tool_name": "PowerShell", "tool_input": {"command": "Get-Content .\\data\\raw.csv"}})
    r = run(exe, "hook-guard", stdin=blocked)
    ok &= check(r.returncode == 2 and "원자료" in r.stderr, "hook-guard 차단", f"{r.returncode} {r.stderr}")
    allowed = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls output/tables"}})
    r = run(exe, "hook-guard", stdin=allowed)
    ok &= check(r.returncode == 0, "hook-guard 통과", f"{r.returncode} {r.stderr}")

    r = run(exe, "setup", "--yes", "--dry-run", "--clients", "none", "--com", "no", "--no-install")
    ok &= check(r.returncode == 0 and "[5/5]" in r.stdout, "setup --dry-run", r.stdout[-500:] + r.stderr[-500:])

    r = run(exe, "configure", "--clients", "codex", "--dry-run")
    ok &= check(r.returncode == 0 and "원본 스킬 없음" not in r.stdout, "묶은 스킬", r.stdout[-500:])

    if args.mcpb:
        with zipfile.ZipFile(args.mcpb) as zf:
            names = set(zf.namelist())
            man = json.loads(zf.read("manifest.json"))
        ok &= check("server/stata-agent.exe" in names, ".mcpb 실행파일 포함", str(sorted(names)[:10]))
        ok &= check(sorted(t["name"] for t in man["tools"]) == EXPECTED and man["version"] == __version__,
                    ".mcpb manifest 도구·버전")

    print("전체: " + ("통과" if ok else "실패"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
