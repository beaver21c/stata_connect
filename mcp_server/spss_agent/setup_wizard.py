"""SPSS 설치 도우미 — Stata판(stata_agent.setup_wizard)과 같은 흐름. SPSS는 화면 연동(COM) 단계 없음.

단계
1. 실행파일을 고정 위치(%LOCALAPPDATA%\\SpssAgent)로 복사
2. SPSS 확인(설치 폴더·버전·동봉 Python 2.7/3.x·지원 범위 22 이상)
3. (선택) 분석 폴더 생성(규약 폴더·지침·Claude Code 권한·실행 전 검사)
4. 설치된 AI 앱에 연결(Claude Code·Codex 설정 병합, 기존 설정 백업). Claude 데스크톱 앱(채팅)은 .mcpb 확장 권장

실행 방식
- 더블클릭: 질문에 답하며 진행(끝에 Enter 대기)
- Claude Code가 대신 실행(플러그인 /spss-agent:setup):
  ``setup --yes --clients claude-code-project --no-skill --project <분석 폴더>``
상태: 자동 테스트, Windows 실기 미검증
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stata_agent.client_config import Change, configure_all, merge_project_mcp
from stata_agent.resources import is_frozen
from stata_agent.setup_wizard import (
    CLIENT_LABELS,
    Ask,
    Out,
    _client_list,
    _yes,
    desktop_app_present,
    install_self,
)

from . import __version__
from .discovery import discover
from .project import init_project
from .resources import SPSS
from .tool_specs import PROFILE, SERVER_NAME


@dataclass
class SpssSetupOptions:
    yes: bool = False
    clients: str = "auto"             # auto | none | claude-code,claude-code-project,codex,claude-desktop
    install: bool = True
    skill: bool = True
    project: str | None = None
    spss_home: str | None = None      # SPSS 설치 폴더 지정 → 서버 env SPSS_AGENT_HOME
    spss_python: str | None = None    # SPSS 동봉 Python 지정 → 서버 env SPSS_AGENT_PYTHON
    dry_run: bool = False
    pause: bool = False


@dataclass
class SpssSetupResult:
    exe: Path | None
    spss_found: bool
    python_ready: bool
    changes: list[Change]
    errors: list[str]


def _pinned_env(opts: SpssSetupOptions) -> dict[str, str]:
    env = {}
    if opts.spss_home:
        env["SPSS_AGENT_HOME"] = opts.spss_home
    if opts.spss_python:
        env["SPSS_AGENT_PYTHON"] = opts.spss_python
    return env


def run_setup(opts: SpssSetupOptions, ask: Ask = input, out: Out = print) -> SpssSetupResult:
    import os

    errors: list[str] = []
    changes: list[Change] = []
    out(f"SPSS 에이전트 설치 도우미 {__version__}" + (" (점검만, 변경 없음)" if opts.dry_run else ""))
    out("-" * 60)

    # 1
    out("[1/4] 실행파일 설치")
    exe: Path | None = None
    if opts.install:
        exe, msg = install_self(opts.dry_run, dest=SPSS.installed_exe())
        out("  " + msg)
        if exe is None and is_frozen():
            errors.append(msg)
    else:
        out("  생략(--no-install)")

    # 2
    out("[2/4] SPSS 확인")
    if opts.spss_python:
        os.environ["SPSS_AGENT_PYTHON"] = opts.spss_python  # 이 실행 안의 탐지에 반영
    installs, chosen = discover(opts.spss_home)
    python_ready = bool(chosen and chosen.python_ready)
    if chosen is None:
        out("  SPSS Statistics를 찾지 못함 → 나중에 설치하거나, 확장 설정의 'SPSS 설치 폴더'에 경로 지정")
    else:
        py = f"동봉 Python {chosen.python_line}: {chosen.python_exe}" if python_ready else "동봉 Python 없음"
        out(f"  {chosen.home} (버전 {chosen.version or '미확인'}, {py})")
        if not python_ready:
            out("  → SPSS 설치 때 'Python Essentials'(Integration Plug-in for Python) 포함 여부 확인,"
                " 다른 위치면 --spss-python으로 지정")
        if chosen.supported is False:
            out("  주의: SPSS 22 미만은 지원 범위 밖")
        if len(installs) > 1:
            out(f"  (다른 설치 {len(installs) - 1}개 있음, 최신·지원 버전 우선 선택)")

    # 3
    out("[3/4] 분석 폴더")
    project_root: Path | None = None
    if opts.project:
        project_root = Path(opts.project).expanduser()
        if opts.dry_run:
            out(f"  준비 예정: {project_root}")
        else:
            project_root.mkdir(parents=True, exist_ok=True)
            created = init_project(project_root, hook=SPSS.hook_command(exe))
            out(f"  {project_root}: " + (", ".join(created) if created else "이미 준비됨"))
    else:
        out("  생략(AI에게 '이 폴더로 분석 시작'이라고 하면 spss_open_session이 자동 생성)")

    # 4
    out("[4/4] AI 앱 연결")
    env = _pinned_env(opts)
    server = SPSS.self_command(exe)
    server.env.update(env)
    clients = _client_list(opts)  # type: ignore[arg-type] — clients 속성만 사용
    if not clients:
        out("  연결할 앱 없음(Claude Code·Codex 미감지)")
    for client in clients:
        label = CLIENT_LABELS.get(client, client)
        if client == "claude-code-project":
            if project_root is None:
                errors.append("claude-code-project: --project 필요")
                out("  Claude Code(분석 폴더): --project 경로가 없어 생략")
                continue
            pcmd = SPSS.project_command(exe)
            pcmd.env.update(env)
            c = merge_project_mcp(project_root, pcmd, name=SERVER_NAME, dry_run=opts.dry_run)
            out(f"  [{c.action}] {c.target} {c.detail}" + (f" (백업: {c.backup})" if c.backup else ""))
            if c.action == "error":
                errors.append(f"{c.target}: {c.detail}")
            changes.append(c)
            continue
        if not _yes(f"  {label}에 연결할까?", opts, ask):  # type: ignore[arg-type]
            out(f"  {label}: 생략")
            continue
        result = configure_all(server, SPSS.skill_source(), [client], opts.dry_run,
                               profile=PROFILE, install_skills=opts.skill)
        for c in result:
            out(f"  [{c.action}] {c.target} {c.detail}" + (f" (백업: {c.backup})" if c.backup else ""))
            if c.action == "error":
                errors.append(f"{c.target}: {c.detail}")
        changes.extend(result)
    if desktop_app_present() and "claude-desktop" not in clients:
        out("  Claude 데스크톱 앱(채팅) 감지 → 설명서 SPSS 페이지의 '.mcpb 확장' 파일을 더블클릭해 설치")

    out("-" * 60)
    if errors:
        out("일부 단계 실패: " + " / ".join(errors))
    else:
        out("준비 완료 → 사용하는 AI 앱(Claude·Codex)을 완전히 종료한 뒤 다시 실행할 것")
    if opts.pause and not opts.yes:
        try:
            ask("Enter를 누르면 창이 닫힘")
        except EOFError:
            pass
    return SpssSetupResult(exe, chosen is not None, python_ready, changes, errors)
