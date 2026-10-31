"""클라이언트 설정 자동 병합(설계서 §11). 원칙: 기존 설정 백업 후 병합(덮어쓰기 금지), 완료 후 재시작 안내.

근거(docs/IMPLEMENTATION_STATUS.md §근거 참조)
- Claude Code: ``claude mcp add --transport stdio --scope user <name> -- <command>`` (공식 문서 확인).
  사용자 범위 설정은 ``~/.claude.json``에 저장되나 내부 키 경로는 문서 미기재 → 직접 편집하지 않고 CLI 사용.
  스킬: ``~/.claude/skills/<name>/SKILL.md``. 권한: ``~/.claude/settings.json``의 permissions.allow/ask.
- Claude Desktop: ``claude_desktop_config.json``의 ``mcpServers``(형식은 공식 문서 예시 확인).
  Windows 경로 ``%APPDATA%\\Claude\\``는 공식 문서 미확인 → 폴더가 있을 때만 기록.
- Codex: ``~/.codex/config.toml``(CODEX_HOME 우선) ``[mcp_servers.<name>]``, 도구별
  ``[mcp_servers.<name>.tools.<tool>] approval_mode``(openai/codex 소스 확인). 스킬: ``~/.agents/skills/``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .tool_specs import APPROVAL_TOOLS, READ_ONLY_TOOLS, SERVER_NAME, client_tool_id

SKILL_NAME = "stata-analysis"


@dataclass(frozen=True)
class ClientProfile:
    """클라이언트에 등록할 MCP 서버 묶음(패키지별: Stata·SPSS)."""

    server_name: str
    skill_name: str
    read_only_tools: tuple[str, ...]
    approval_tools: tuple[str, ...]

    def tool_id(self, tool: str) -> str:
        return f"mcp__{self.server_name}__{tool}"


STATA_PROFILE = ClientProfile(SERVER_NAME, SKILL_NAME, tuple(READ_ONLY_TOOLS), tuple(APPROVAL_TOOLS))


@dataclass
class Change:
    target: str
    action: str  # "created" | "updated" | "unchanged" | "skipped" | "planned" | "error"
    detail: str = ""
    backup: str | None = None


@dataclass
class ServerCommand:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(path: Path) -> str | None:
    if not path.exists():
        return None
    dest = path.with_name(f"{path.name}.bak-{_stamp()}")
    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)
    return str(dest)


# ── JSON(Claude Desktop·Claude Code settings) ────────────────────

def merge_desktop_config(config_path: Path, server: ServerCommand, name: str = SERVER_NAME,
                         dry_run: bool = False) -> Change:
    data: dict = {}
    if config_path.is_file():
        text = config_path.read_text(encoding="utf-8").strip()
        if text:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                return Change(str(config_path), "error", f"JSON 해석 실패 → 수동 확인 필요: {e}")
    entry = {"command": server.command, "args": list(server.args)}
    if server.env:
        entry["env"] = dict(server.env)
    servers = data.setdefault("mcpServers", {})
    if servers.get(name) == entry:
        return Change(str(config_path), "unchanged")
    action = "updated" if config_path.exists() else "created"
    if dry_run:
        return Change(str(config_path), "planned", f"mcpServers.{name} 기록 예정")
    servers[name] = entry
    bak = backup(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return Change(str(config_path), action, f"mcpServers.{name} 기록", bak)


def merge_claude_permissions(settings_path: Path, dry_run: bool = False,
                             profile: ClientProfile = STATA_PROFILE) -> Change:
    data: dict = {}
    if settings_path.is_file():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            return Change(str(settings_path), "error", f"JSON 해석 실패: {e}")
    perms = data.setdefault("permissions", {})
    before = json.dumps(perms, sort_keys=True)
    for key, names in (("allow", profile.read_only_tools), ("ask", profile.approval_tools)):
        current = list(perms.get(key, []))
        for n in names:
            rule = profile.tool_id(n)
            if rule not in current:
                current.append(rule)
        perms[key] = current
    if json.dumps(perms, sort_keys=True) == before:
        return Change(str(settings_path), "unchanged")
    if dry_run:
        return Change(str(settings_path), "planned", "읽기 도구 allow·실행 도구 ask 규칙 추가 예정")
    bak = backup(settings_path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return Change(str(settings_path), "updated" if bak else "created", "권한 규칙 병합", bak)


def merge_project_mcp(project_root: Path, server: ServerCommand, name: str = SERVER_NAME,
                      dry_run: bool = False) -> Change:
    """분석 폴더의 ``.mcp.json``(Claude Code 프로젝트 범위)에 서버 추가.

    근거(Claude Code 공식 문서 mcp): type 없는 항목 = stdio 서버, command·args·env에 ``${VAR}`` 확장 가능,
    처음 사용할 때 승인 창 표시. 도구 이름이 ``mcp__<서버>__<도구>``로 유지되어 프로젝트 권한 규칙과 맞음
    (플러그인에 넣으면 ``mcp__plugin_<플러그인>_<서버>__<도구>``로 바뀜).
    """
    path = Path(project_root) / ".mcp.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            return Change(str(path), "error", f"JSON 해석 실패 → 수동 확인 필요: {e}")
    servers = data.setdefault("mcpServers", {})
    entry: dict = {"command": server.command, "args": list(server.args)}
    if server.env:
        entry["env"] = dict(server.env)
    if servers.get(name) == entry:
        return Change(str(path), "unchanged", f"mcpServers.{name} 동일")
    existed = name in servers
    servers[name] = entry
    if dry_run:
        return Change(str(path), "planned", f"mcpServers.{name} {'교체' if existed else '추가'}")
    bak = backup(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return Change(str(path), "updated" if bak else "created", f"mcpServers.{name} {'교체' if existed else '추가'}", bak)


# ── TOML(Codex) ──────────────────────────────────────────────────

def _toml_str(value: str) -> str:
    if "'" not in value and "\n" not in value:
        return f"'{value}'"  # 리터럴 문자열: Windows 경로 역슬래시 그대로
    return json.dumps(value, ensure_ascii=False)


def render_codex_block(server: ServerCommand, name: str = SERVER_NAME,
                       startup_timeout: float = 60.0, tool_timeout: float = 900.0,
                       read_only_tools: tuple[str, ...] | None = None) -> str:
    lines = [
        f"[mcp_servers.{name}]",
        f"command = {_toml_str(server.command)}",
        "args = [" + ", ".join(_toml_str(a) for a in server.args) + "]",
        f"startup_timeout_sec = {startup_timeout:.1f}",
        f"tool_timeout_sec = {tool_timeout:.1f}",
        'default_tools_approval_mode = "prompt"',
    ]
    if server.env:
        lines.append("")
        lines.append(f"[mcp_servers.{name}.env]")
        lines += [f"{k} = {_toml_str(v)}" for k, v in server.env.items()]
    for tool in (READ_ONLY_TOOLS if read_only_tools is None else read_only_tools):
        lines.append("")
        lines.append(f"[mcp_servers.{name}.tools.{tool}]")
        lines.append('approval_mode = "approve"')
    return "\n".join(lines) + "\n"


def _header_belongs(header: str, name: str) -> bool:
    inner = header.strip()[1:-1].strip()
    inner = re.sub(r'"([^"]*)"', r"\1", inner)  # [mcp_servers."stata"] 형식 허용
    return inner == f"mcp_servers.{name}" or inner.startswith(f"mcp_servers.{name}.")


def remove_codex_block(text: str, name: str = SERVER_NAME) -> tuple[str, bool]:
    out, removed, skipping = [], False, False
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^\[\[?[^\]]+\]\]?\s*(#.*)?$", stripped):
            header = re.sub(r"\s*#.*$", "", stripped)
            skipping = header.startswith("[") and not header.startswith("[[") and _header_belongs(header, name)
            removed = removed or skipping
        if not skipping:
            out.append(line)
    result = "\n".join(out).rstrip("\n")
    return (result + "\n" if result else ""), removed


def merge_codex_config(config_path: Path, server: ServerCommand, name: str = SERVER_NAME,
                       dry_run: bool = False, read_only_tools: tuple[str, ...] | None = None) -> Change:
    original = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    stripped, existed = remove_codex_block(original, name)
    block = render_codex_block(server, name, read_only_tools=read_only_tools)
    new_text = (stripped + ("\n" if stripped else "") + block) if stripped else block
    if new_text == original:
        return Change(str(config_path), "unchanged")
    if sys.version_info >= (3, 11):
        import tomllib

        try:
            tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as e:
            return Change(str(config_path), "error", f"병합 결과 TOML 검증 실패(원본 유지): {e}")
    if dry_run:
        return Change(str(config_path), "planned", f"[mcp_servers.{name}] {'교체' if existed else '추가'} 예정")
    bak = backup(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(new_text, encoding="utf-8")
    return Change(str(config_path), "updated" if original else "created",
                  f"[mcp_servers.{name}] {'교체' if existed else '추가'}", bak)


# ── 스킬 복사 ────────────────────────────────────────────────────

def install_skill(src: Path, dest_root: Path, dry_run: bool = False, skill_name: str = SKILL_NAME) -> Change:
    dest = dest_root / skill_name
    if not (src / "SKILL.md").is_file():
        return Change(str(dest), "error", f"원본 스킬 없음: {src}")
    if dry_run:
        return Change(str(dest), "planned", "스킬 복사 예정")
    bak = None
    if dest.exists():
        bak = backup(dest)
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return Change(str(dest), "updated" if bak else "created", "스킬 복사", bak)


# ── 경로 ────────────────────────────────────────────────────────

def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def claude_desktop_config_path() -> Path | None:
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return None


def register_claude_code(server: ServerCommand, name: str = SERVER_NAME, dry_run: bool = False) -> Change:
    exe = shutil.which("claude")
    # -e는 가변 인자 → 이름 뒤에 두어야 이름을 삼키지 않음(CLI 도움말 예시: add my-server -e K=v -- cmd)
    cmd = ["claude", "mcp", "add", "--transport", "stdio", "--scope", "user", name]
    for k, v in server.env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["--", server.command, *server.args]
    if exe is None:
        return Change("claude CLI", "skipped", "claude 명령 없음 → 수동 등록: " + " ".join(cmd))
    if dry_run:
        return Change("claude CLI", "planned", " ".join(cmd))
    subprocess.run([exe, "mcp", "remove", "--scope", "user", name], capture_output=True, check=False)
    r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return Change("claude CLI", "error", (r.stderr or r.stdout).strip()[:500])
    return Change("claude CLI", "updated", f"사용자 범위 MCP 서버 '{name}' 등록")


def configure_all(server: ServerCommand, skill_src: Path, clients: list[str],
                  dry_run: bool = False, force_desktop: bool = False,
                  profile: ClientProfile = STATA_PROFILE, install_skills: bool = True) -> list[Change]:
    """install_skills=False: 스킬은 플러그인(Claude Code)·업로드 등 다른 경로로 설치한 경우(중복 방지)."""
    changes: list[Change] = []
    name = profile.server_name
    if "claude-code" in clients:
        changes.append(register_claude_code(server, name=name, dry_run=dry_run))
        changes.append(merge_claude_permissions(Path.home() / ".claude" / "settings.json", dry_run, profile))
        if install_skills:
            changes.append(install_skill(skill_src, Path.home() / ".claude" / "skills", dry_run, profile.skill_name))
    if "claude-desktop" in clients:
        path = claude_desktop_config_path()
        if path is None:
            changes.append(Change("Claude Desktop", "skipped", "이 운영체제의 설정 경로 미정"))
        elif not path.parent.is_dir() and not force_desktop:
            changes.append(Change(str(path), "skipped", "Claude Desktop 설정 폴더 없음(미설치 또는 경로 상이) → --force-desktop으로 강제"))
        else:
            changes.append(merge_desktop_config(path, server, name=name, dry_run=dry_run))
    if "codex" in clients:
        changes.append(merge_codex_config(codex_home() / "config.toml", server, name=name, dry_run=dry_run,
                                          read_only_tools=profile.read_only_tools))
        if install_skills:
            changes.append(install_skill(skill_src, Path.home() / ".agents" / "skills", dry_run, profile.skill_name))
    return changes
