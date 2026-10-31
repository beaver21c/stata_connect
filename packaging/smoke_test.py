"""빌드한 실행파일 점검(Stata·SPSS 없이) — CI windows 작업에서 실행. 제품: stata·spss.

공통
1. --version 일치
2. doctor --json: JSON 출력(Stata는 등록자·일련번호 항목 없음 + 화면 연동 계층 포함 여부)
3. MCP 서버: ``serve``와 인자 없음(입력 연결) 두 방식으로 초기화 + 도구 목록 = tool_specs
4. hook-guard: 원자료 명령 차단(종료 코드 2), 일반 명령 통과(0)
5. setup --dry-run: 질문 없이 끝까지 진행
6. 묶은 스킬: configure --dry-run에서 스킬 원본 오류 없음
7. (선택) .mcpb: manifest.json·server/<제품>-agent.exe 포함, 도구 목록·버전 일치
SPSS만
8. 실행파일 → 엔진 스크립트 → 가짜 spss 모듈(tests/fake_spss_home)까지 MCP 도구 호출로 세션 열기·문법 실행

사용: python packaging/smoke_test.py <실행파일> [--product stata|spss] [--mcpb <파일>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))

from spss_agent.tool_specs import TOOLS as SPSS_TOOLS  # noqa: E402
from stata_agent import __version__  # noqa: E402
from stata_agent.tool_specs import TOOLS as STATA_TOOLS  # noqa: E402

EXPECTED = {"stata": sorted(t.name for t in STATA_TOOLS), "spss": sorted(t.name for t in SPSS_TOOLS)}
SETUP_ARGS = {
    "stata": ["setup", "--yes", "--dry-run", "--clients", "none", "--com", "no", "--no-install"],
    "spss": ["setup", "--yes", "--dry-run", "--clients", "none", "--no-install"],
}
SETUP_LAST_STEP = {"stata": "[5/5]", "spss": "[4/4]"}


def run(exe: str, *args: str, stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run([exe, *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _params(exe: str, args: list[str], env: dict | None = None):
    from mcp import StdioServerParameters
    from mcp.client.stdio import get_default_environment

    full = get_default_environment()
    full.update(env or {})
    return StdioServerParameters(command=exe, args=args, env=full)


async def list_tools(exe: str, args: list[str]) -> list[str]:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(_params(exe, args)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return sorted(t.name for t in tools.tools)


async def spss_engine_roundtrip(exe: str, env: dict, project: Path) -> list[str]:
    """MCP 도구 호출 → 실행파일 안 서버 → 엔진 스크립트(동봉 Python 대신 이 점검의 Python) → 가짜 spss 모듈."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    texts = []
    async with stdio_client(_params(exe, ["serve"], env)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for name, args in (
                ("spss_open_session", {"project_dir": str(project)}),
                ("spss_write_syntax", {"filename": "01_t.sps", "sections": [
                    {"title": "자료", "code": "DATA LIST FREE / x.\nBEGIN DATA\n1 2 3 4\nEND DATA.\nEXECUTE."},
                    {"title": "기술통계", "code": "DESCRIPTIVES VARIABLES=x."}]}),
                ("spss_run_section", {"filename": "01_t.sps", "section_id": "S01"}),
                ("spss_run_section", {"filename": "01_t.sps", "section_id": "S02"}),
            ):
                res = await session.call_tool(name, args)
                texts.append(" ".join(getattr(c, "text", "") for c in res.content) + (" [오류]" if res.isError else ""))
    return texts


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
    ap.add_argument("--product", choices=("stata", "spss"), default="stata")
    ap.add_argument("--mcpb")
    args = ap.parse_args()
    exe = str(Path(args.exe).resolve())
    prod = args.product
    ok = True

    r = run(exe, "--version")
    ok &= check(r.stdout.strip() == __version__, "버전", r.stdout + r.stderr)

    r = run(exe, *(["doctor", "--json", "--no-about"] if prod == "stata" else ["doctor", "--json"]))
    try:
        text = r.stdout
        data = json.loads(text)
        ok &= check("installs" in data and "licensed_to" not in text and "serial" not in text,
                    "doctor --json(등록자·일련번호 없음)", text[:300])
        if prod == "stata":
            layer = data.get("com_layer") or {}
            # 상류 모듈·배포 정보(--copy-metadata) 묶음 확인, Windows는 pywin32까지
            need_pywin32 = sys.platform.startswith("win")
            ok &= check(layer.get("upstream") is True and (layer.get("pywin32") is True or not need_pywin32),
                        "화면 연동 계층 포함(stata-gui-mcp" + ("·pywin32)" if need_pywin32 else ")"),
                        json.dumps(layer, ensure_ascii=False))
    except ValueError:
        ok &= check(False, "doctor --json", r.stdout[:300] + r.stderr[:300])

    for label, a in (("MCP serve", ["serve"]), ("MCP 인자 없음", [])):
        try:
            names = asyncio.run(asyncio.wait_for(list_tools(exe, a), 120))
            ok &= check(names == EXPECTED[prod], label, f"{names}")
        except Exception as e:  # noqa: BLE001 — 점검 보고용
            ok &= check(False, label, repr(e))

    blocked = json.dumps({"tool_name": "PowerShell", "tool_input": {"command": "Get-Content .\\data\\raw.csv"}})
    r = run(exe, "hook-guard", stdin=blocked)
    ok &= check(r.returncode == 2 and "원자료" in r.stderr, "hook-guard 차단", f"{r.returncode} {r.stderr}")
    allowed = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls output/tables"}})
    r = run(exe, "hook-guard", stdin=allowed)
    ok &= check(r.returncode == 0, "hook-guard 통과", f"{r.returncode} {r.stderr}")

    r = run(exe, *SETUP_ARGS[prod])
    ok &= check(r.returncode == 0 and SETUP_LAST_STEP[prod] in r.stdout, "setup --dry-run",
                r.stdout[-500:] + r.stderr[-500:])

    r = run(exe, "configure", "--clients", "codex", "--dry-run")
    ok &= check(r.returncode == 0 and "원본 스킬 없음" not in r.stdout, "묶은 스킬", r.stdout[-500:])

    if args.mcpb:
        with zipfile.ZipFile(args.mcpb) as zf:
            names = set(zf.namelist())
            man = json.loads(zf.read("manifest.json"))
        ok &= check(f"server/{prod}-agent.exe" in names, ".mcpb 실행파일 포함", str(sorted(names)[:10]))
        ok &= check(sorted(t["name"] for t in man["tools"]) == EXPECTED[prod] and man["version"] == __version__,
                    ".mcpb manifest 도구·버전")

    if prod == "spss":
        work = Path(tempfile.mkdtemp(prefix="sa_smoke_"))
        try:
            home = work / "SPSS"
            shutil.copytree(ROOT / "tests" / "fake_spss_home", home)
            (home / "stats.exe").write_text("")
            project = work / "proj"
            project.mkdir()
            env = {"SPSS_AGENT_HOME": str(home), "SPSS_AGENT_PYTHON": sys.executable,
                   "STATA_AGENT_REPORT_DIR": str(work / "reports")}
            texts = asyncio.run(asyncio.wait_for(spss_engine_roundtrip(exe, env, project), 180))
            joined = "\n".join(texts)
            ok &= check("[오류]" not in joined and "2.50" in texts[-1],
                        "SPSS 엔진 왕복(실행파일 → 엔진 → 가짜 spss)", joined[-800:])
        except Exception as e:  # noqa: BLE001
            ok &= check(False, "SPSS 엔진 왕복", repr(e))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        os.environ.pop("SPSS_AGENT_PYTHON", None)

    print("전체: " + ("통과" if ok else "실패"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
