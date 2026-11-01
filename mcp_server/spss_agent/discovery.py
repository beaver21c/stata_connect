"""SPSS Statistics 설치 탐지.

근거 [2차 확인: 제3자 구현 spss-mcp-extended 2.0.0 소스]
- 실행파일: ``C:\\Program Files\\IBM\\SPSS Statistics\\<버전>\\stats.exe`` 또는 ``...\\SPSS Statistics\\stats.exe``
- 레지스트리: ``SOFTWARE\\IBM\\SPSS Statistics\\<버전>``의 ``InstallationDirectory``
- 내장 Python: ``<설치폴더>\\Python3\\python.exe``
구버전 경로 ``IBM\\SPSS\\Statistics\\<버전>``은 [논리적 추론]으로 추가.

지원 범위 SPSS 22 이상(사용자 요구). 버전별 내장 Python [2차 확인: IBM 문서 검색 요약]
- 22·23: Python 2.7, 24~26: 2.7 + 3.4, 27부터: 3.x만(2.x 제외), 최신 문서: 3.10
- 폴더 이름: 3.x는 ``Python3``(제3자 구현 확인), 2.7은 ``Python`` [미확인: 실기 확인 필요]
  → ``Python3`` → ``Python`` → ``Python27`` 순으로 찾고, ``SPSS_AGENT_PYTHON``으로 직접 지정 가능
- 32비트판(22 등)은 ``Program Files (x86)``·레지스트리 ``WOW6432Node`` [논리적 추론]
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
MIN_SUPPORTED_VERSION = 22
PYTHON_DIRS = ("Python3", "Python", "Python27")
REGISTRY_KEYS = (
    r"SOFTWARE\IBM\SPSS Statistics",
    r"SOFTWARE\IBM\SPSS\Statistics",
    r"SOFTWARE\WOW6432Node\IBM\SPSS Statistics",
    r"SOFTWARE\WOW6432Node\IBM\SPSS\Statistics",
)
REGISTRY_VALUES = ("InstallationDirectory", "InstallDir")


def _env(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip()
    return None if not value or re.fullmatch(r"\$\{[^}]*\}", value) else value


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
        """SPSS 동봉 Python. SPSS_AGENT_PYTHON 지정이 있으면 우선(파일이 있을 때만)."""
        override = _env("SPSS_AGENT_PYTHON")
        if override and Path(override).is_file():
            return Path(override)
        for d in PYTHON_DIRS:
            p = Path(self.home) / d / "python.exe"
            if p.is_file():
                return p
        return Path(self.home) / ("Python" if (self.version or 99) <= 23 else "Python3") / "python.exe"

    @property
    def python_ready(self) -> bool:
        return self.python_exe.is_file()

    @property
    def python_line(self) -> str:
        """폴더 이름 기준 추정(Python3 = 3.x, 그 밖 = 2.7)."""
        return "3.x" if self.python_exe.parent.name.lower() == "python3" else "2.7"

    @property
    def supported(self) -> bool | None:
        return None if self.version is None else self.version >= MIN_SUPPORTED_VERSION

    def public_dict(self) -> dict:
        return {"home": self.home, "version": self.version, "source": self.source,
                "python_ready": self.python_ready, "python_line": self.python_line if self.python_ready else None,
                "supported": self.supported}


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
            for key_path in REGISTRY_KEYS:
                try:
                    key = winreg.OpenKey(hive, key_path)
                except OSError:
                    continue
                with key:
                    i = 0
                    while True:
                        try:
                            ver = winreg.EnumKey(key, i)
                        except OSError:
                            break
                        i += 1
                        home = _registry_home(winreg, key, ver)
                        if home and (Path(home) / "stats.exe").is_file():
                            v = int(re.match(r"\d+", ver).group()) if re.match(r"\d+", ver) else _version_of(home)
                            out.append(SpssInstall(str(Path(home)), v, "registry"))
    except ImportError:
        pass
    return out


def _registry_home(winreg, key, ver: str) -> str | None:
    try:
        with winreg.OpenKey(key, ver) as vk:
            for name in REGISTRY_VALUES:
                try:
                    home, _ = winreg.QueryValueEx(vk, name)
                    return str(home)
                except OSError:
                    continue
    except OSError:
        return None
    return None


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
    # 지원 범위(22 이상)·Python 준비 우선, 그다음 최신 버전
    return max(usable, key=lambda i: (i.supported is not False, i.version or 0)) if usable else None


def discover(preferred_home: str | None = None) -> tuple[list[SpssInstall], SpssInstall | None]:
    preferred_home = preferred_home or _env("SPSS_AGENT_HOME")
    installs = scan()
    return installs, choose(installs, preferred_home)
