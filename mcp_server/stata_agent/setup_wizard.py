"""설치 도우미(설계서 §0.4·§11) — 처음 쓰는 사람이 사전 준비를 한 번의 실행으로 끝내도록 묶은 절차.

단계
1. 실행파일을 고정 위치(%LOCALAPPDATA%\\StataAgent)로 복사 → 설정 파일이 가리킬 경로 고정
2. Stata 탐지(설치·에디션·버전·라이선스). 등록자·일련번호는 출력하지 않음
3. Stata 화면 연동(COM) 등록 — 관리자 승인(UAC) 1회. 거절해도 배치 실행으로 동작
4. (선택) 분석 폴더 생성(규약 폴더·지침·Claude Code 권한·실행 전 검사)
5. 설치된 AI 앱에 연결(기존 설정 백업 후 병합): Claude 앱(채팅) 설정 파일 직접 기록 — 일반판·Microsoft Store판
   위치 자동 감지(§17), Claude Code·Codex
6. 원자료 보호 보강: Desktop Commander(Claude 앱의 PC 명령 실행 도구) 차단 목록에 Stata 실행파일 추가(§17)

실행 방식
- 더블클릭: 질문에 답하며 진행(끝에 Enter 대기)
- Claude Code가 대신 실행(플러그인 /stata-agent:setup):
  ``setup --yes --com no --clients claude-code-project --no-skill --project <분석 폴더>``
상태: 단계별 함수는 자동 테스트, Windows 실기(UAC·복사·앱 연결) 미검증
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .client_config import (
    DESKTOP_CONFIG,
    Change,
    claude_desktop_config_paths,
    codex_home,
    configure_all,
    find_claude_cli,
    merge_project_mcp,
)
from .dc_guard import DC_NOTICE, STATA_COMMANDS, add_blocked_commands
from .discovery import IS_WINDOWS, com_registration, discover, version_declaration
from .project import init_project
from .resources import hook_command, installed_exe, is_frozen, project_command, self_command, skill_source

CLIENT_LABELS = {
    "claude-code": "Claude Code(모든 폴더, claude 명령 필요)",
    "claude-code-project": "Claude Code(분석 폴더 .mcp.json)",
    "codex": "Codex",
    "claude-desktop": "Claude 앱(채팅)",
}
_ACTION_WORDS = {"created": "등록 완료", "updated": "등록 완료", "unchanged": "이미 등록됨", "planned": "등록 예정",
                 "skipped": "생략", "error": "실패"}


def describe_change(c: Change) -> str:
    """설치 화면 표시용. Claude 앱 설정은 쉬운 말로(설치 형태·결과), 그 밖은 기존 형식."""
    target = c.target.replace("\\", "/")
    if target.endswith(DESKTOP_CONFIG):
        kind = "Microsoft Store판" if "/Packages/Claude_" in target else "일반 설치"
        line = f"  Claude 앱({kind}): {_ACTION_WORDS.get(c.action, c.action)}"
        if c.action == "error":
            line += f" — {c.detail}"
        line += f"\n    설정 파일: {c.target}" + (f"\n    이전 설정 백업: {c.backup}" if c.backup else "")
        return line
    if c.target == "Claude 앱":
        return f"  Claude 앱: {_ACTION_WORDS.get(c.action, c.action)} — {c.detail}"
    return f"  [{c.action}] {c.target} {c.detail}" + (f" (백업: {c.backup})" if c.backup else "")


def protect_desktop_commander(commands: tuple[str, ...], product: str, opts, ask, out) -> list[str]:
    """6단계 공통(Stata·SPSS): Desktop Commander 설정이 있으면 차단 목록 보강 + 끄기 안내. 반환: 오류."""
    preview = add_blocked_commands(commands, dry_run=True)
    if preview.action == "skipped":
        out("  Desktop Commander 미사용 → 생략")
        return []
    if preview.action == "unchanged":
        out(f"  Desktop Commander: {product} 실행 차단 이미 설정됨")
        out("  ※ " + DC_NOTICE)
        return []
    if preview.action == "error":
        out(f"  Desktop Commander: {preview.detail}")
        return [f"Desktop Commander: {preview.detail}"]
    if not _yes(f"  Claude 앱의 Desktop Commander(PC 명령 실행 도구)가 {product}를 직접 실행하지 못하게 막을까?",
                opts, ask):
        out("  생략 — ※ " + DC_NOTICE)
        return []
    c = add_blocked_commands(commands, dry_run=opts.dry_run)
    words = {"updated": "차단 추가 완료", "planned": "차단 추가 예정", "unchanged": "이미 차단됨", "error": "실패"}
    out(f"  Desktop Commander: {words.get(c.action, c.action)}"
        + (f" — {c.detail}" if c.detail else "") + (f" (이전 설정 백업: {c.backup})" if c.backup else ""))
    out("  ※ " + DC_NOTICE)
    return [f"Desktop Commander: {c.detail}"] if c.action == "error" else []


FINISH_TEXT = (
    "준비 완료. 남은 일:\n"
    "  1) Claude 앱을 완전히 종료 — 창을 닫은 뒤 화면 오른쪽 아래 알림 영역에 Claude 아이콘이 남아 있으면 그 메뉴에서 종료\n"
    "  2) Claude 앱을 다시 실행 → 채팅창에 '{product} 연결 점검해줘' 입력\n"
    "  (Codex·Claude Code를 쓰면 그 앱도 다시 실행)"
)


@dataclass
class SetupOptions:
    yes: bool = False                 # 질문 없이 기본값(예)으로 진행
    clients: str = "auto"             # auto | 콤마 목록(claude-code,codex,claude-desktop) | none
    com: str = "ask"                  # ask | yes | no
    install: bool = True              # 실행파일 고정 위치 복사(실행파일 형태일 때만)
    skill: bool = True                # 스킬 복사(Claude Code·Codex)
    project: str | None = None        # 분석 폴더 생성 경로
    stata_exe: str | None = None      # Stata 실행파일 지정(자동 탐지 실패·여러 버전일 때) → 서버 env로 기록
    dry_run: bool = False
    pause: bool = False               # 끝에 Enter 대기(더블클릭 실행)


@dataclass
class SetupResult:
    exe: Path | None
    stata_found: bool
    com_registered: bool
    changes: list[Change]
    errors: list[str]


Ask = Callable[[str], str]
Out = Callable[[str], None]


def _yes(question: str, opts: SetupOptions, ask: Ask, default: bool = True) -> bool:
    if opts.yes:
        return default
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = ask(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes", "예", "ㅇ", "네")


# ── 1. 실행파일 고정 위치 ─────────────────────────────────────────

def _cleanup_old_copies(dest: Path) -> None:
    """이전 재설치 때 옆으로 옮겨 둔 실행파일(사용 중이라 바로 못 지운 것) 정리. 아직 사용 중이면 그대로 둠."""
    for old in dest.parent.glob(f"{dest.stem}.old-*{dest.suffix}"):
        try:
            old.unlink()
        except OSError:
            pass


def install_self(dry_run: bool = False, src: Path | None = None, dest: Path | None = None) -> tuple[Path | None, str]:
    """실행파일 형태면 고정 위치로 복사하고 그 경로 반환. 개발판·pip 설치는 복사하지 않음(None).

    재설치 대응(§18): 이전 버전이 Claude 앱·Claude Code에서 실행 중이면 Windows는 덮어쓰기를 막음 →
    실행 중인 파일은 이름 바꾸기가 허용되므로 옆으로 옮긴 뒤 새 파일을 둠(옛 파일은 다음 실행 때 정리).
    복사는 같은 폴더 임시 파일 → 교체 순서라 도중에 끊겨도 설치 파일이 깨지지 않음.
    """
    if src is None:
        if not is_frozen():
            return None, "개발판(파이썬 실행) → 복사 생략, 현재 명령 사용"
        src = Path(sys.executable)
    dest = dest or installed_exe()
    try:
        if src.resolve() == dest.resolve():
            return dest, f"이미 고정 위치에서 실행 중: {dest}"
    except OSError:
        pass
    if dry_run:
        return dest, f"복사 예정: {src} → {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_old_copies(dest)
    tmp = dest.with_name(f"{dest.stem}.new-{os.getpid()}{dest.suffix}")
    try:
        shutil.copy2(src, tmp)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return None, f"복사 실패: {e} (디스크 공간·백신 프로그램 확인)"
    replaced_running = False
    try:
        os.replace(tmp, dest)
    except PermissionError:
        # 이전 버전 실행 중 → 옆으로 옮기고 교체
        try:
            dest.rename(dest.with_name(f"{dest.stem}.old-{int(time.time())}{dest.suffix}"))
            os.replace(tmp, dest)
            replaced_running = True
        except OSError:
            tmp.unlink(missing_ok=True)
            return None, (f"교체 실패(사용 중): {dest} → Claude·Codex 앱을 완전히 종료한 뒤 설치 도우미를 다시 실행")
    note = " (이전 버전이 실행 중이라 앱을 다시 시작하면 새 버전으로 바뀜)" if replaced_running else ""
    return dest, f"설치 완료: {dest}{note}"


# ── 3. COM 등록 ──────────────────────────────────────────────────

def com_register_command(stata_exe: str, unregister: bool = False) -> list[str]:
    """관리자 승인 창(UAC)을 띄워 ``<Stata> /Register``를 실행하는 PowerShell 명령.

    근거: Stata 안내의 ``/Register``(해제 ``/Unregister``) 사용(installer/register_com.ps1과 같은 동작).
    """
    flag = "/Unregister" if unregister else "/Register"
    quoted = stata_exe.replace("'", "''")
    script = f"Start-Process -FilePath '{quoted}' -ArgumentList '{flag}' -Verb RunAs -Wait"
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]


def register_com(stata_exe: str, unregister: bool = False, runner=subprocess.run) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "Windows 전용 기능"
    r = runner(com_register_command(stata_exe, unregister), capture_output=True, text=True, check=False)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, "등록 취소 또는 실패" + (f": {detail[-1][:200]}" if detail else "")
    reg = com_registration()
    if unregister:
        return (not reg.registered), ("해제 완료" if not reg.registered else "해제 후에도 등록 정보 남음")
    if reg.registered:
        return True, f"등록 완료: {reg.server_path}"
    return False, "등록 확인 실패 → Stata를 관리자 권한으로 실행해 수동 등록 필요"


# ── 4. 앱 감지 ───────────────────────────────────────────────────

def detect_clients() -> list[str]:
    found: list[str] = []
    if claude_desktop_config_paths():
        found.append("claude-desktop")
    if find_claude_cli():
        found.append("claude-code")
    if shutil.which("codex") or codex_home().is_dir():
        found.append("codex")
    return found


def desktop_app_present() -> bool:
    return bool(claude_desktop_config_paths())


def _client_list(opts: SetupOptions) -> list[str]:
    if opts.clients == "none":
        return []
    if opts.clients == "auto":
        return detect_clients()
    return [c.strip() for c in opts.clients.split(",") if c.strip()]


# ── 전체 절차 ────────────────────────────────────────────────────

def run_setup(opts: SetupOptions, ask: Ask = input, out: Out = print) -> SetupResult:
    errors: list[str] = []
    changes: list[Change] = []
    out(f"Stata 에이전트 설치 도우미 {__version__}" + (" (점검만, 변경 없음)" if opts.dry_run else ""))
    out("-" * 60)

    # 1
    out("[1/6] 실행파일 설치")
    exe: Path | None = None
    if opts.install:
        exe, msg = install_self(opts.dry_run)
        out("  " + msg)
        if exe is None and is_frozen():
            errors.append(msg)
    else:
        out("  생략(--no-install)")

    # 2
    out("[2/6] Stata 확인")
    rep = discover(run_about_checks=not opts.dry_run, preferred_exe=opts.stata_exe)
    sel = rep.selected
    if sel is None:
        out("  Stata를 찾지 못함 → Stata 설치 후 이 설치 도우미를 다시 실행(설치 위치가 특이하면 --stata-exe로 지정)")
    else:
        about = sel.about
        desc = f"{sel.exe} ({sel.edition or '에디션 미확인'})"
        if about and about.parsed:
            valid = {True: "유효", False: "만료/거부", None: "미확인"}[about.license_valid()]
            desc += f" {about.product} {about.version}, 라이선스 {valid}"
        out("  " + desc)
        out(f"  do-file 버전 선언: {version_declaration(sel)}")
        if sel.supported is False:
            out("  주의: Stata 17 미만은 지원 범위 밖(표 내보내기 etable·collect 등 17 이상 기능 사용)")

    # 3
    out("[3/6] Stata 화면 연동(COM) 등록")
    com_ok = rep.com.registered
    if not IS_WINDOWS:
        out("  Windows 전용 → 생략(배치 실행 사용)")
    elif com_ok:
        out(f"  이미 등록됨: {rep.com.server_path}")
    elif sel is None:
        out("  Stata가 없어 생략")
    elif opts.com == "no":
        out("  생략(배치 실행으로 동작, 나중에 'stata-agent register-com'으로 등록 가능)")
    else:
        want = opts.com == "yes" or _yes(
            "  분석 과정을 Stata 창에서 보려면 등록이 필요함. 관리자 승인 창이 뜸. 등록할까?", opts, ask)
        if not want:
            out("  생략(배치 실행으로 동작)")
        elif opts.dry_run:
            out("  등록 예정: " + " ".join(com_register_command(sel.exe)))
        else:
            com_ok, msg = register_com(sel.exe)
            out("  " + msg)
            if not com_ok:
                out("  → 배치 실행으로 계속 동작함(화면 연동만 제외)")

    # 4
    out("[4/6] 분석 폴더")
    project_root: Path | None = None
    if opts.project:
        project_root = Path(opts.project).expanduser()
        if opts.dry_run:
            out(f"  준비 예정: {project_root}")
        else:
            project_root.mkdir(parents=True, exist_ok=True)
            created = init_project(project_root, version_declaration(sel), hook=hook_command(exe))
            out(f"  {project_root}: " + (", ".join(created) if created else "이미 준비됨"))
    else:
        out("  생략(AI에게 '이 폴더로 분석 시작'이라고 하면 stata_open_session이 자동 생성)")

    # 5
    out("[5/6] AI 앱 연결")
    server = self_command(exe)
    pinned_env = {"STATA_AGENT_STATA_EXE": opts.stata_exe} if opts.stata_exe else {}
    server.env.update(pinned_env)
    clients = _client_list(opts)
    if not clients:
        out("  연결할 앱 없음(Claude 앱·Claude Code·Codex 미감지 → 앱 설치 후 한 번 실행하고 다시 실행)")
    for client in clients:
        label = CLIENT_LABELS.get(client, client)
        if client == "claude-code-project":
            if project_root is None:
                errors.append("claude-code-project: --project 필요")
                out("  Claude Code(분석 폴더): --project 경로가 없어 생략")
                continue
            pcmd = project_command(exe)
            pcmd.env.update(pinned_env)
            c = merge_project_mcp(project_root, pcmd, dry_run=opts.dry_run)
            out(describe_change(c))
            if c.action == "error":
                errors.append(f"{c.target}: {c.detail}")
            changes.append(c)
            continue
        if not _yes(f"  {label}에 연결할까?", opts, ask):
            out(f"  {label}: 생략")
            continue
        result = configure_all(server, skill_source(), [client], opts.dry_run, install_skills=opts.skill)
        for c in result:
            out(describe_change(c))
            if c.action == "error":
                errors.append(f"{c.target}: {c.detail}")
        changes.extend(result)

    # 6
    out("[6/6] 원자료 보호(다른 AI 도구)")
    errors += protect_desktop_commander(STATA_COMMANDS, "Stata", opts, ask, out)

    out("-" * 60)
    if errors:
        out("일부 단계 실패: " + " / ".join(errors))
    else:
        out(FINISH_TEXT.format(product="Stata"))
    if opts.pause and not opts.yes:
        try:
            ask("Enter를 누르면 창이 닫힘")
        except EOFError:
            pass
    return SetupResult(exe, sel is not None, com_ok, changes, errors)
