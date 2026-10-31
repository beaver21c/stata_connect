"""명령줄 도구(개발·시험용). 최종 사용자는 설치 프로그램이 같은 동작을 수행(설계서 §0·§11).

stata-agent doctor            Stata 설치·라이선스·COM 등록 점검(등록자는 이 화면에만 표시)
stata-agent selftest          T1~T10 자가 점검 + 보고서 저장
stata-agent init-project DIR  규약 폴더 생성(--example: auto 예제 포함)
stata-agent configure ...     Claude Code·Claude Desktop·Codex 설정 병합(백업 후)
stata-agent render-templates  plugins/stata-agent/skills/stata-analysis/templates 갱신
stata-agent serve             MCP 서버(stdio) 실행 = stata-agent-mcp
stata-agent setup             설치 도우미(실행파일 고정·Stata 확인·COM 등록·앱 연결)
stata-agent register-com      Stata 화면 연동(COM) 등록(관리자 승인 창)
stata-agent hook-guard        Claude Code 셸 명령 실행 전 검사(프로젝트 설정이 호출)

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
    from .discovery import discover, version_declaration

    rep = discover(run_about_checks=not args.no_about, preferred_exe=args.exe)
    if args.json:
        print(json.dumps({"version": __version__, **rep.public_dict(),
                          "version_declaration": version_declaration(rep.selected),
                          "com_layer": _com_layer_status()}, ensure_ascii=False, indent=2))
        return 0 if rep.selected else 1
    # 등록자는 사람이 보는 콘솔 화면에만 표시(출력이 다른 프로그램·AI로 넘어가면 생략)
    show_registrant = sys.stdout.isatty()
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
            if about.licensed_to and show_registrant:
                line += f"\n    등록자(로컬 표시 전용): {' / '.join(about.licensed_to)}"
        elif inst.about_error:
            line += f" — {inst.about_error}"
        if inst.supported is False:
            line += " [지원 범위 밖: Stata 17 이상 필요]"
        print(line)
    print(f"선택: {rep.selected.exe if rep.selected else '없음'} / do-file 선언: {version_declaration(rep.selected)}")
    return 0 if rep.selected else 1


def _com_layer_status() -> dict:
    """화면 연동 계층(상류 stata-gui-mcp·pywin32)을 불러올 수 있는지. 실행파일 묶음 누락 점검용."""
    from .backends.com_gui import load_upstream

    try:
        up = load_upstream()
    except Exception as e:  # noqa: BLE001 — 진단 출력
        return {"upstream": False, "pywin32": None, "detail": f"{type(e).__name__}: {e}"[:300]}
    ready = bool(getattr(up, "PYWIN32_READY", False))
    return {"upstream": True, "pywin32": ready, "detail": "" if ready else str(getattr(up, "PYWIN32_ERROR", ""))[:300]}


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
    from .resources import hook_command

    line = f"version {args.version}" if args.version else version_declaration(None)
    created = init_project(root, line, example=args.example, hook=None if args.no_hook else hook_command())
    print("생성: " + (", ".join(created) if created else "없음(이미 존재)"))
    return 0


def cmd_configure(args) -> int:
    from .client_config import ServerCommand, configure_all
    from .resources import self_command, skill_source

    env = dict(kv.split("=", 1) for kv in args.env or [])
    if args.command:
        server = ServerCommand(args.command, list(args.arg or []), env)
    else:
        server = self_command()
        server.env.update(env)
    skill_src = Path(args.skill_src) if args.skill_src else skill_source()
    clients = [c.strip() for c in args.clients.split(",") if c.strip()]
    changes = configure_all(server, skill_src, clients, args.dry_run, args.force_desktop,
                            install_skills=not args.no_skill)
    for c in changes:
        print(f"[{c.action}] {c.target} {c.detail}" + (f" (백업: {c.backup})" if c.backup else ""))
    if not args.dry_run:
        print("\n완료 → Claude·Codex 앱을 완전히 종료한 뒤 다시 실행할 것(설정 재로드).")
        if "claude-desktop" in clients:
            print("Claude 앱 스킬은 Customize > Skills에서 stata-analysis 폴더 ZIP을 1회 업로드해야 함.")
    return 1 if any(c.action == "error" for c in changes) else 0


def cmd_render_templates(args) -> int:
    from .project import rendered_templates

    dest = Path(args.dest) if args.dest else _repo_root() / "plugins" / "stata-agent" / "skills" / "stata-analysis" / "templates"
    dest.mkdir(parents=True, exist_ok=True)
    for name, content in rendered_templates().items():
        (dest / name).write_text(content, encoding="utf-8")
        print(f"갱신: {dest / name}")
    return 0


def cmd_serve(args) -> int:
    from .server import main as serve_main

    serve_main()
    return 0


def cmd_setup(args) -> int:
    from .setup_wizard import SetupOptions, run_setup

    opts = SetupOptions(yes=args.yes, clients=args.clients, com=args.com, install=not args.no_install,
                        skill=not args.no_skill, project=args.project, dry_run=args.dry_run, pause=args.pause,
                        stata_exe=args.stata_exe)
    result = run_setup(opts)
    return 1 if result.errors else 0


def cmd_register_com(args) -> int:
    from .discovery import discover
    from .setup_wizard import register_com

    exe = args.exe
    if not exe:
        rep = discover(run_about_checks=False)
        exe = rep.selected.exe if rep.selected else None
    if not exe:
        print("Stata 실행파일을 찾지 못함 → --exe 경로 지정")
        return 1
    ok, msg = register_com(exe, unregister=args.unregister)
    print(msg)
    return 0 if ok else 1


def cmd_hook_guard(args) -> int:
    from .hookguard import main as hook_main

    return hook_main()


def _default_argv(argv: list[str] | None) -> list[str] | None:
    """인자 없이 실행된 경우: 콘솔(더블클릭)이면 설치 도우미, 입력이 연결돼 있으면(MCP 클라이언트) 서버."""
    if argv is None and len(sys.argv) <= 1:
        try:
            interactive = sys.stdin is not None and sys.stdin.isatty()
        except (AttributeError, ValueError):
            interactive = False
        return ["setup", "--pause"] if interactive else ["serve"]
    return argv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stata-agent", description="Stata 에이전트 도구")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="Stata 설치·라이선스·COM 점검")
    d.add_argument("--exe", help="Stata 실행파일 지정")
    d.add_argument("--no-about", action="store_true", help="about 배치 실행 생략")
    d.add_argument("--json", action="store_true", help="기계용 출력(등록자·일련번호 제외)")
    d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("selftest", help="T1~T10 자가 점검")
    s.add_argument("--client", help="사용 앱 이름")
    s.add_argument("--no-batch", action="store_true")
    s.set_defaults(func=cmd_selftest)

    i = sub.add_parser("init-project", help="규약 폴더 생성")
    i.add_argument("dir")
    i.add_argument("--example", action="store_true")
    i.add_argument("--version", type=int, help="do-file version 선언(예: 18)")
    i.add_argument("--no-hook", action="store_true", help="Claude Code 실행 전 검사 등록 생략")
    i.set_defaults(func=cmd_init_project)

    c = sub.add_parser("configure", help="클라이언트 설정 병합")
    c.add_argument("--clients", default="claude-code,claude-desktop,codex")
    c.add_argument("--command", help="MCP 서버 실행 명령(기본: 실행파일이면 '<exe> serve', 아니면 stata-agent-mcp)")
    c.add_argument("--arg", action="append", help="--command에 붙일 인자(반복 가능)")
    c.add_argument("--no-skill", action="store_true", help="스킬 복사 생략(플러그인으로 설치한 경우)")
    c.add_argument("--env", action="append", help="KEY=VALUE (반복 가능)")
    c.add_argument("--skill-src", help="스킬 폴더(기본: 저장소 plugins/stata-agent/skills/stata-analysis)")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--force-desktop", action="store_true")
    c.set_defaults(func=cmd_configure)

    r = sub.add_parser("render-templates", help="스킬 템플릿 갱신")
    r.add_argument("--dest")
    r.set_defaults(func=cmd_render_templates)

    v = sub.add_parser("serve", help="MCP 서버 실행")
    v.set_defaults(func=cmd_serve)

    st = sub.add_parser("setup", help="설치 도우미")
    st.add_argument("--yes", action="store_true", help="질문 없이 기본값으로 진행")
    st.add_argument("--clients", default="auto",
                    help="auto | none | claude-code,claude-code-project,codex,claude-desktop")
    st.add_argument("--com", choices=("ask", "yes", "no"), default="ask", help="COM 등록 여부")
    st.add_argument("--no-install", action="store_true", help="실행파일 고정 위치 복사 생략")
    st.add_argument("--no-skill", action="store_true", help="스킬 복사 생략(플러그인으로 설치한 경우)")
    st.add_argument("--project", help="분석 폴더 생성 경로")
    st.add_argument("--stata-exe", help="Stata 실행파일 지정(자동 탐지 실패·여러 버전일 때)")
    st.add_argument("--dry-run", action="store_true", help="점검만(변경 없음)")
    st.add_argument("--pause", action="store_true", help="끝에 Enter 대기")
    st.set_defaults(func=cmd_setup)

    rc = sub.add_parser("register-com", help="Stata 화면 연동(COM) 등록")
    rc.add_argument("--exe", help="Stata 실행파일(기본: 탐지 결과)")
    rc.add_argument("--unregister", action="store_true")
    rc.set_defaults(func=cmd_register_com)

    hg = sub.add_parser("hook-guard", help="Claude Code 실행 전 검사(stdin JSON)")
    hg.set_defaults(func=cmd_hook_guard)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(_default_argv(argv))
    if args.func is not cmd_serve:
        _utf8_when_piped()
    sys.exit(args.func(args))


def _utf8_when_piped() -> None:
    """출력이 다른 프로그램(Claude Code 등)으로 넘어갈 때 UTF-8로 고정(Windows 기본 코드페이지 회피).
    콘솔 화면 출력은 그대로 둠. MCP 서버(serve)는 SDK가 UTF-8로 직접 처리."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
