"""SPSS Statistics 설치 탐지.

근거 [2차 확인: 제3자 구현 spss-mcp-extended 2.0.0 소스]
- 실행파일: ``C:\\Program Files\\IBM\\SPSS Statistics\\<버전>\\stats.exe`` 또는 ``...\\SPSS Statistics\\stats.exe``
- 레지스트리: ``SOFTWARE\\IBM\\SPSS Statistics\\<버전>``의 ``InstallationDirectory``
- 내장 Python: ``<설치폴더>\\Python3\\python.exe``
구버전 경로 ``IBM\\SPSS\\Statistics\\<버전>``은 [논리적 추론]으로 추가.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")


@dataclass
class SpssInstall:
    home: str  # stats.exe가 있는 폴더
    version: int | None
    source: str  # scan | registry | user

    @property
    def stats_exe(self) -> Path:
        return Path(self.home) / "stats.exe"

    @property
    def python_exe(self) -> Path:
        return Path(self.home) / "Python3" / "python.exe"

    @property
    def python_ready(self) -> bool:
        return self.python_exe.is_file()

    def public_dict(self) -> dict:
        return {"home": self.home, "version": self.version, "source": self.source,
                "python_ready": self.python_ready}


def _version_of(path: str) -> int | None:
    for part in reversed(Path(path).parts):
        if re.fullmatch(r"\d{2}", part):
            return int(part)
    return None


def candidate_roots() -> list[str]:
    roots = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(env)
        if v and v not in roots:
            roots.append(v)
    return roots or [r"C:\Program Files", r"C:\Program Files (x86)"]


def scan(roots: list[str] | None = None) -> list[SpssInstall]:
    found: dict[str, SpssInstall] = {}
    for root in roots if roots is not None else (candidate_roots() if IS_WINDOWS else []):
        for base in (Path(root) / "IBM" / "SPSS Statistics", Path(root) / "IBM" / "SPSS" / "Statistics"):
            if not base.is_dir():
                continue
            if (base / "stats.exe").is_file():
                found.setdefault(os.path.normcase(str(base)), SpssInstall(str(base), _version_of(str(base)), "scan"))
            for child in base.iterdir():
                if child.is_dir() and (child / "stats.exe").is_file():
                    found.setdefault(os.path.normcase(str(child)), SpssInstall(str(child), _version_of(str(child)), "scan"))
    for inst in registry():
        found.setdefault(os.path.normcase(inst.home), inst)
    return list(found.values())


def registry() -> list[SpssInstall]:
    if not IS_WINDOWS:
        return []
    out = []
    try:
        import winreg  # type: ignore

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\IBM\SPSS Statistics") as key:
                    i = 0
                    while True:
                        try:
                            ver = winreg.EnumKey(key, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(key, ver) as vk:
                                home, _ = winreg.QueryValueEx(vk, "InstallationDirectory")
                        except OSError:
                            continue
                        if (Path(home) / "stats.exe").is_file():
                            v = int(re.match(r"\d+", ver).group()) if re.match(r"\d+", ver) else _version_of(home)
                            out.append(SpssInstall(str(Path(home)), v, "registry"))
            except OSError:
                continue
    except ImportError:
        pass
    return out


def choose(installs: list[SpssInstall], preferred_home: str | None = None) -> SpssInstall | None:
    if preferred_home:
        p = Path(preferred_home)
        home = p.parent if p.name.lower() == "stats.exe" else p
        for inst in installs:
            if os.path.normcase(inst.home) == os.path.normcase(str(home)):
                return inst
        if (home / "stats.exe").is_file():
            return SpssInstall(str(home), _version_of(str(home)), "user")
    usable = [i for i in installs if i.python_ready] or installs
    return max(usable, key=lambda i: i.version or 0) if usable else None


def discover(preferred_home: str | None = None) -> tuple[list[SpssInstall], SpssInstall | None]:
    preferred_home = preferred_home or os.environ.get("SPSS_AGENT_HOME") or None
    installs = scan()
    return installs, choose(installs, preferred_home)
