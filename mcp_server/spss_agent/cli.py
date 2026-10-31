"""spss-agent 명령줄 도구(개발·시험용).

spss-agent doctor            SPSS 설치·내장 Python 탐지
spss-agent selftest          T1~T10 자가 점검 + 보고서
spss-agent init-project DIR  규약 폴더 생성(--example: 예제 포함)
spss-agent configure ...     Claude Code·Desktop·Codex에 spss 서버 등록(백업 후 병합)
spss-agent render-templates  plugins/spss-agent/skills/spss-analysis/templates 갱신
spss-agent serve             MCP 서버(stdio) = spss-agent-mcp
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cmd_doctor(args) -> int:
    from .discovery import discover

    installs, chosen = discover(args.home)
    print(f"spss-agent {__version__} doctor")
    if not installs and not chosen:
        print("SPSS Statistics 설치를 찾지 못함 → --home으로 설치 폴더 지정")
        return 1
    for inst in installs + ([chosen] if chosen and chosen not in installs else []):
        mark = "*" if inst is chosen else " "
        print(f"{mark} {inst.home} [{inst.source}] 버전 {inst.version or '?'} / 내장 Python {'있음' if inst.python_ready else '없음'}")
    return 0 if chosen and chosen.python_ready else 1


def cmd_selftest(args) -> int:
    from stata_agent.report import save_report
    from stata_agent.selftest import results_table

    from .selftest import run_selftest
    from .service import SpssAgentService

    svc = SpssAgentService()
    results, meta = run_selftest(svc, args.client, not args.no_batch)
    print(results_table(results))
    print(f"\n점검 보고서: {save_report(results, meta, svc.settings.report_dir)}")
    return 1 if any(r.status == "fail" for r in results) else 0


def cmd_init_project(args) -> int:
    from .project import init_project

    root = Path(args.dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    created = init_project(root, example=args.example)
    print("생성: " + (", ".join(created) if created else "없음(이미 존재)"))
    return 0


def cmd_configure(args) -> int:
    from stata_agent.client_config import ServerCommand, configure_all

    from .tool_specs import PROFILE

    command = args.command or shutil.which("spss-agent-mcp") or "spss-agent-mcp"
    env = dict(kv.split("=", 1) for kv in args.env or [])
    skill_src = Path(args.skill_src) if args.skill_src else _repo_root() / "plugins" / "spss-agent" / "skills" / "spss-analysis"
    clients = [c.strip() for c in args.clients.split(",") if c.strip()]
    changes = configure_all(ServerCommand(command, [], env), skill_src, clients, args.dry_run, args.force_desktop,
                            profile=PROFILE)
    for c in changes:
        print(f"[{c.action}] {c.target} {c.detail}" + (f" (백업: {c.backup})" if c.backup else ""))
    if not args.dry_run:
        print("\n완료 → Claude·Codex 앱을 완전히 종료한 뒤 다시 실행할 것.")
    return 1 if any(c.action == "error" for c in changes) else 0


def cmd_render_templates(args) -> int:
    from .project import rendered_templates
    from .syntaxfile import ENCODING

    dest = Path(args.dest) if args.dest else _repo_root() / "plugins" / "spss-agent" / "skills" / "spss-analysis" / "templates"
    dest.mkdir(parents=True, exist_ok=True)
    for name, content in rendered_templates().items():
        (dest / name).write_text(content, encoding=ENCODING if name.endswith(".sps") else "utf-8")
        print(f"갱신: {dest / name}")
    return 0


def cmd_serve(args) -> int:
    from .server import main as serve_main

    serve_main()
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="spss-agent", description="SPSS 에이전트 도구")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor")
    d.add_argument("--home", help="SPSS 설치 폴더(stats.exe 위치)")
    d.set_defaults(func=cmd_doctor)
    s = sub.add_parser("selftest")
    s.add_argument("--client")
    s.add_argument("--no-batch", action="store_true")
    s.set_defaults(func=cmd_selftest)
    i = sub.add_parser("init-project")
    i.add_argument("dir")
    i.add_argument("--example", action="store_true")
    i.set_defaults(func=cmd_init_project)
    c = sub.add_parser("configure")
    c.add_argument("--clients", default="claude-code,claude-desktop,codex")
    c.add_argument("--command")
    c.add_argument("--env", action="append")
    c.add_argument("--skill-src")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--force-desktop", action="store_true")
    c.set_defaults(func=cmd_configure)
    r = sub.add_parser("render-templates")
    r.add_argument("--dest")
    r.set_defaults(func=cmd_render_templates)
    v = sub.add_parser("serve")
    v.set_defaults(func=cmd_serve)
    args = p.parse_args(argv)
    sys.exit(args.func(args))
