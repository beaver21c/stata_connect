"""명령줄 도구(개발·시험용). 최종 사용자는 설치 프로그램이 같은 동작을 수행(설계서 §0·§11).

stata-agent doctor            Stata 설치·라이선스·COM 등록 점검(등록자는 이 화면에만 표시)
stata-agent selftest          T1~T10 자가 점검 + 보고서 저장
stata-agent init-project DIR  규약 폴더 생성(--example: auto 예제 포함)
stata-agent configure ...     Claude Code·Claude Desktop·Codex 설정 병합(백업 후)
stata-agent render-templates  skills/stata-analysis/templates 갱신
stata-agent serve             MCP 서버(stdio) 실행 = stata-agent-mcp
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
    from .discovery import discover, version_declaration

    rep = discover(run_about_checks=not args.no_about, preferred_exe=args.exe)
    print(f"stata-agent {__version__} doctor")
    print(f"COM 등록: {'예' if rep.com.registered else '아니오'}"
          f" {rep.com.server_path or rep.com.error or ''}")
    if not rep.installs:
        print("Stata 설치를 찾지 못함 → --exe 경로 지정")
        return 1
    for inst in rep.installs:
        mark = "*" if inst is rep.selected else " "
        about = inst.about
        line = f"{mark} {inst.exe} [{inst.source}] {inst.edition or '?'}"
        if about and about.parsed:
            valid = {True: "유효", False: "만료/거부", None: "미확인"}[about.license_valid()]
            line += f" {about.product} {about.version} 라이선스 {valid}"
            line += f" (만료 {about.expires})" if about.expires else (" (영구)" if about.perpetual else "")
            if about.licensed_to:
                line += f"\n    등록자(로컬 표시 전용): {' / '.join(about.licensed_to)}"
        elif inst.about_error:
            line += f" — {inst.about_error}"
        print(line)
    print(f"선택: {rep.selected.exe if rep.selected else '없음'} / do-file 선언: {version_declaration(rep.selected)}")
    return 0 if rep.selected else 1


def cmd_selftest(args) -> int:
    from .report import save_report
    from .selftest import results_table, run_selftest
    from .service import StataAgentService

    svc = StataAgentService()
    results, meta = run_selftest(svc, args.client, not args.no_batch)
    print(results_table(results))
    path = save_report(results, meta, svc.settings.report_dir)
    print(f"\n점검 보고서: {path}")
    return 1 if any(r.status == "fail" for r in results) else 0


def cmd_init_project(args) -> int:
    from .discovery import version_declaration
    from .project import init_project

    root = Path(args.dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    line = f"version {args.version}" if args.version else version_declaration(None)
    created = init_project(root, line, example=args.example)
    print("생성: " + (", ".join(created) if created else "없음(이미 존재)"))
    return 0


def cmd_configure(args) -> int:
    from .client_config import ServerCommand, configure_all

    command = args.command or shutil.which("stata-agent-mcp") or "stata-agent-mcp"
    env = dict(kv.split("=", 1) for kv in args.env or [])
    skill_src = Path(args.skill_src) if args.skill_src else _repo_root() / "skills" / "stata-analysis"
    clients = [c.strip() for c in args.clients.split(",") if c.strip()]
    changes = configure_all(ServerCommand(command, [], env), skill_src, clients, args.dry_run, args.force_desktop)
    for c in changes:
        print(f"[{c.action}] {c.target} {c.detail}" + (f" (백업: {c.backup})" if c.backup else ""))
    if not args.dry_run:
        print("\n완료 → Claude·Codex 앱을 완전히 종료한 뒤 다시 실행할 것(설정 재로드).")
        if "claude-desktop" in clients:
            print("Claude 앱 스킬은 Customize > Skills에서 stata-analysis 폴더 ZIP을 1회 업로드해야 함.")
    return 1 if any(c.action == "error" for c in changes) else 0


def cmd_render_templates(args) -> int:
    from .project import rendered_templates

    dest = Path(args.dest) if args.dest else _repo_root() / "skills" / "stata-analysis" / "templates"
    dest.mkdir(parents=True, exist_ok=True)
    for name, content in rendered_templates().items():
        (dest / name).write_text(content, encoding="utf-8")
        print(f"갱신: {dest / name}")
    return 0


def cmd_serve(args) -> int:
    from .server import main as serve_main

    serve_main()
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="stata-agent", description="Stata 에이전트 도구")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Stata 설치·라이선스·COM 점검")
    d.add_argument("--exe", help="Stata 실행파일 지정")
    d.add_argument("--no-about", action="store_true", help="about 배치 실행 생략")
    d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("selftest", help="T1~T10 자가 점검")
    s.add_argument("--client", help="사용 앱 이름")
    s.add_argument("--no-batch", action="store_true")
    s.set_defaults(func=cmd_selftest)

    i = sub.add_parser("init-project", help="규약 폴더 생성")
    i.add_argument("dir")
    i.add_argument("--example", action="store_true")
    i.add_argument("--version", type=int, help="do-file version 선언(예: 18)")
    i.set_defaults(func=cmd_init_project)

    c = sub.add_parser("configure", help="클라이언트 설정 병합")
    c.add_argument("--clients", default="claude-code,claude-desktop,codex")
    c.add_argument("--command", help="MCP 서버 실행 명령(기본: PATH의 stata-agent-mcp)")
    c.add_argument("--env", action="append", help="KEY=VALUE (반복 가능)")
    c.add_argument("--skill-src", help="스킬 폴더(기본: 저장소 skills/stata-analysis)")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--force-desktop", action="store_true")
    c.set_defaults(func=cmd_configure)

    r = sub.add_parser("render-templates", help="스킬 템플릿 갱신")
    r.add_argument("--dest")
    r.set_defaults(func=cmd_render_templates)

    v = sub.add_parser("serve", help="MCP 서버 실행")
    v.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    sys.exit(args.func(args))
