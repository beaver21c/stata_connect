"""spss-agent 명령줄 도구(개발·시험용).

spss-agent doctor            SPSS 설치·내장 Python 탐지
spss-agent selftest          T1~T10 자가 점검 + 보고서
spss-agent init-project DIR  규약 폴더 생성(--example: 예제 포함)
spss-agent configure ...     Claude Code·Desktop·Codex에 spss 서버 등록(백업 후 병합)
spss-agent render-templates  plugins/spss-agent/skills/spss-analysis/templates 갱신
spss-agent serve             MCP 서버(stdio) = spss-agent-mcp
spss-agent setup             설치 도우미(실행파일 고정·SPSS 확인·분석 폴더·앱 연결)
spss-agent hook-guard        Claude Code 셸 명령 실행 전 검사(프로젝트 설정이 호출, Stata판과 공용)

인자 없이 실행: 콘솔에서 연 경우(더블클릭) 설치 도우미, 입력이 연결된 경우(MCP 클라이언트) 서버
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cmd_doctor(args) -> int:
    from .discovery import discover

    installs, chosen = discover(args.home)
    if args.json:
        print(json.dumps({"version": __version__, "installs": [i.public_dict() for i in installs],
                          "selected": chosen.public_dict() if chosen else None}, ensure_ascii=False, indent=2))
        return 0 if chosen and chosen.python_ready else 1
    print(f"spss-agent {__version__} doctor")
    if not installs and not chosen:
        print("SPSS Statistics 설치를 찾지 못함 → --home으로 설치 폴더 지정")
        return 1
    for inst in installs + ([chosen] if chosen and chosen not in installs else []):
        mark = "*" if inst is chosen else " "
        py = f"있음({inst.python_line}: {inst.python_exe})" if inst.python_ready else "없음"
        warn = " [지원 범위 밖: SPSS 22 이상 필요]" if inst.supported is False else ""
        print(f"{mark} {inst.home} [{inst.source}] 버전 {inst.version or '?'} / 내장 Python {py}{warn}")
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
    from .resources import SPSS

    created = init_project(root, example=args.example, hook=None if args.no_hook else SPSS.hook_command())
    print("생성: " + (", ".join(created) if created else "없음(이미 존재)"))
    return 0


def cmd_configure(args) -> int:
    from stata_agent.client_config import ServerCommand, configure_all

    from .resources import SPSS
    from .tool_specs import PROFILE

    env = dict(kv.split("=", 1) for kv in args.env or [])
    if args.command:
        server = ServerCommand(args.command, list(args.arg or []), env)
    else:
        server = SPSS.self_command()
        server.env.update(env)
    skill_src = Path(args.skill_src) if args.skill_src else SPSS.skill_source()
    clients = [c.strip() for c in args.clients.split(",") if c.strip()]
    changes = configure_all(server, skill_src, clients, args.dry_run, args.force_desktop,
                            profile=PROFILE, install_skills=not args.no_skill)
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


def cmd_setup(args) -> int:
    from .setup_wizard import SpssSetupOptions, run_setup

    opts = SpssSetupOptions(yes=args.yes, clients=args.clients, install=not args.no_install, skill=not args.no_skill,
                            project=args.project, spss_home=args.spss_home, spss_python=args.spss_python,
                            dry_run=args.dry_run, pause=args.pause)
    return 1 if run_setup(opts).errors else 0


def cmd_hook_guard(args) -> int:
    from stata_agent.hookguard import main as hook_main

    return hook_main()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spss-agent", description="SPSS 에이전트 도구")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor")
    d.add_argument("--home", help="SPSS 설치 폴더(stats.exe 위치)")
    d.add_argument("--json", action="store_true", help="기계용 출력")
    d.set_defaults(func=cmd_doctor)
    s = sub.add_parser("selftest")
    s.add_argument("--client")
    s.add_argument("--no-batch", action="store_true")
    s.set_defaults(func=cmd_selftest)
    i = sub.add_parser("init-project")
    i.add_argument("dir")
    i.add_argument("--example", action="store_true")
    i.add_argument("--no-hook", action="store_true", help="Claude Code 실행 전 검사 등록 생략")
    i.set_defaults(func=cmd_init_project)
    c = sub.add_parser("configure")
    c.add_argument("--clients", default="claude-code,claude-desktop,codex")
    c.add_argument("--command")
    c.add_argument("--arg", action="append", help="--command에 붙일 인자(반복 가능)")
    c.add_argument("--env", action="append")
    c.add_argument("--no-skill", action="store_true", help="스킬 복사 생략(플러그인으로 설치한 경우)")
    c.add_argument("--skill-src")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--force-desktop", action="store_true")
    c.set_defaults(func=cmd_configure)
    r = sub.add_parser("render-templates")
    r.add_argument("--dest")
    r.set_defaults(func=cmd_render_templates)
    v = sub.add_parser("serve")
    v.set_defaults(func=cmd_serve)
    st = sub.add_parser("setup", help="설치 도우미")
    st.add_argument("--yes", action="store_true", help="질문 없이 기본값으로 진행")
    st.add_argument("--clients", default="auto",
                    help="auto | none | claude-code,claude-code-project,codex,claude-desktop")
    st.add_argument("--no-install", action="store_true", help="실행파일 고정 위치 복사 생략")
    st.add_argument("--no-skill", action="store_true", help="스킬 복사 생략(플러그인으로 설치한 경우)")
    st.add_argument("--project", help="분석 폴더 생성 경로")
    st.add_argument("--spss-home", help="SPSS 설치 폴더(stats.exe 위치) 지정")
    st.add_argument("--spss-python", help="SPSS 동봉 Python(python.exe) 지정")
    st.add_argument("--dry-run", action="store_true", help="점검만(변경 없음)")
    st.add_argument("--pause", action="store_true", help="끝에 Enter 대기")
    st.set_defaults(func=cmd_setup)
    hg = sub.add_parser("hook-guard", help="Claude Code 실행 전 검사(stdin JSON)")
    hg.set_defaults(func=cmd_hook_guard)
    return p


def main(argv: list[str] | None = None) -> None:
    from stata_agent.cli import _default_argv, _utf8_when_piped

    args = build_parser().parse_args(_default_argv(argv))
    if args.func is not cmd_serve:
        _utf8_when_piped()
    sys.exit(args.func(args))
