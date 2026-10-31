"""실행 형태(저장소 개발판·pip 설치·단일 실행파일)에 따른 경로·실행 명령 결정.

- 단일 실행파일(PyInstaller): ``sys.frozen`` 설정, 묶은 파일은 ``sys._MEIPASS`` 아래
- 저장소 개발판: 스킬 원본은 ``plugins/<플러그인>/skills/<스킬>``
- 설치 위치 고정: 설정 파일이 가리킬 실행파일 경로가 바뀌지 않도록
  ``%LOCALAPPDATA%\\StataAgent\\stata-agent.exe``로 복사(설치 도우미 setup 단계)
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .client_config import ServerCommand

EXE_NAME = "stata-agent.exe"
PLUGIN_NAME = "stata-agent"
SKILL_NAME = "stata-analysis"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path:
    """묶은 자료의 기준 폴더(실행파일이면 압축 해제 폴더, 아니면 저장소)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else repo_root()


def skill_source(plugin: str = PLUGIN_NAME, skill: str = SKILL_NAME) -> Path:
    """설치용 스킬 원본 폴더. 실행파일은 ``skills/<스킬>``로 묶음(packaging/stata_agent.spec)."""
    candidates = [
        bundle_root() / "skills" / skill,
        repo_root() / "plugins" / plugin / "skills" / skill,
    ]
    for c in candidates:
        if (c / "SKILL.md").is_file():
            return c
    return candidates[-1]


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "StataAgent"


def installed_exe() -> Path:
    return install_dir() / EXE_NAME


def self_command(exe: Path | None = None) -> ServerCommand:
    """MCP 클라이언트에 등록할 서버 실행 명령.

    실행파일: ``<exe> serve`` / pip 설치: ``stata-agent-mcp`` / 그 밖: ``<python> -m stata_agent serve``
    """
    if exe is not None:
        return ServerCommand(str(exe), ["serve"])
    if is_frozen():
        return ServerCommand(sys.executable, ["serve"])
    script = shutil.which("stata-agent-mcp")
    if script:
        return ServerCommand(script, [])
    return ServerCommand(sys.executable, ["-m", "stata_agent", "serve"])


def project_command(exe: Path | None = None) -> ServerCommand:
    """분석 폴더 ``.mcp.json``용 명령. 고정 위치 실행파일이면 ``${LOCALAPPDATA}`` 확장을 써서
    사용자 이름이 경로에 남지 않게 함(폴더를 동료와 공유해도 각자 PC에서 동작)."""
    cmd = self_command(exe)
    try:
        if Path(cmd.command).resolve() == installed_exe().resolve():
            return ServerCommand("${LOCALAPPDATA}/StataAgent/" + EXE_NAME, cmd.args, cmd.env)
    except OSError:
        pass
    return cmd


def hook_command(exe: Path | None = None) -> list[str]:
    """Claude Code PreToolUse 검사 명령(실행 형식: 실행파일 + 인자)."""
    if exe is not None:
        return [str(exe), "hook-guard"]
    if is_frozen():
        return [sys.executable, "hook-guard"]
    return [sys.executable, "-m", "stata_agent", "hook-guard"]
