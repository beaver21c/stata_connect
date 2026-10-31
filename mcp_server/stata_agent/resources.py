"""실행 형태(저장소 개발판·pip 설치·단일 실행파일)에 따른 경로·실행 명령 결정. Stata·SPSS 공용.

- 단일 실행파일(PyInstaller): ``sys.frozen`` 설정, 묶은 파일은 ``sys._MEIPASS`` 아래
- 저장소 개발판: 스킬 원본은 ``plugins/<플러그인>/skills/<스킬>``
- 설치 위치 고정: 설정 파일이 가리킬 실행파일 경로가 바뀌지 않도록
  ``%LOCALAPPDATA%\\<폴더>\\<실행파일>``로 복사(설치 도우미 setup 단계)
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .client_config import ServerCommand


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bundle_root() -> Path:
    """묶은 자료의 기준 폴더(실행파일이면 압축 해제 폴더, 아니면 저장소)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else repo_root()


def local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))


@dataclass(frozen=True)
class AppPaths:
    """제품별(Stata·SPSS) 실행파일·설치 폴더·스킬·모듈 이름."""

    exe_name: str      # stata-agent.exe
    dir_name: str      # %LOCALAPPDATA% 아래 폴더
    plugin: str        # plugins/<plugin>
    skill: str         # 스킬 폴더 이름
    module: str        # python -m <module>
    script: str        # pip 설치 시 MCP 서버 명령

    def skill_source(self) -> Path:
        """설치용 스킬 원본 폴더. 실행파일은 ``skills/<스킬>``로 묶음(packaging/build.py)."""
        candidates = [
            bundle_root() / "skills" / self.skill,
            repo_root() / "plugins" / self.plugin / "skills" / self.skill,
        ]
        for c in candidates:
            if (c / "SKILL.md").is_file():
                return c
        return candidates[-1]

    def install_dir(self) -> Path:
        return local_appdata() / self.dir_name

    def installed_exe(self) -> Path:
        return self.install_dir() / self.exe_name

    def self_command(self, exe: Path | None = None) -> ServerCommand:
        """MCP 클라이언트에 등록할 서버 실행 명령.

        실행파일: ``<exe> serve`` / pip 설치: ``<script>`` / 그 밖: ``<python> -m <module> serve``
        """
        if exe is not None:
            return ServerCommand(str(exe), ["serve"])
        if is_frozen():
            return ServerCommand(sys.executable, ["serve"])
        script = shutil.which(self.script)
        if script:
            return ServerCommand(script, [])
        return ServerCommand(sys.executable, ["-m", self.module, "serve"])

    def project_command(self, exe: Path | None = None) -> ServerCommand:
        """분석 폴더 ``.mcp.json``용 명령. 고정 위치 실행파일이면 ``${LOCALAPPDATA}`` 확장을 써서
        사용자 이름이 경로에 남지 않게 함(폴더를 동료와 공유해도 각자 PC에서 동작)."""
        cmd = self.self_command(exe)
        try:
            if Path(cmd.command).resolve() == self.installed_exe().resolve():
                return ServerCommand(f"${{LOCALAPPDATA}}/{self.dir_name}/{self.exe_name}", cmd.args, cmd.env)
        except OSError:
            pass
        return cmd

    def hook_command(self, exe: Path | None = None) -> list[str]:
        """Claude Code PreToolUse 검사 명령(실행 형식: 실행파일 + 인자)."""
        if exe is not None:
            return [str(exe), "hook-guard"]
        if is_frozen():
            return [sys.executable, "hook-guard"]
        return [sys.executable, "-m", self.module, "hook-guard"]


STATA = AppPaths("stata-agent.exe", "StataAgent", "stata-agent", "stata-analysis", "stata_agent", "stata-agent-mcp")

# 기존 호출부 호환(Stata)
EXE_NAME = STATA.exe_name
PLUGIN_NAME = STATA.plugin
SKILL_NAME = STATA.skill


def skill_source(plugin: str = PLUGIN_NAME, skill: str = SKILL_NAME) -> Path:
    return AppPaths(EXE_NAME, STATA.dir_name, plugin, skill, STATA.module, STATA.script).skill_source()


def install_dir() -> Path:
    return STATA.install_dir()


def installed_exe() -> Path:
    return STATA.installed_exe()


def self_command(exe: Path | None = None) -> ServerCommand:
    return STATA.self_command(exe)


def project_command(exe: Path | None = None) -> ServerCommand:
    return STATA.project_command(exe)


def hook_command(exe: Path | None = None) -> list[str]:
    return STATA.hook_command(exe)
