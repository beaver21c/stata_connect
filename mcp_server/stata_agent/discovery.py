"""Stata 설치·에디션·라이선스 탐지(설계서 §6).

1. 설치 탐색: 고정 경로 패턴 + (Windows) 레지스트리 COM 등록 경로
2. 라이선스 확인: 실행파일별 ``about`` 배치 실행 → 버전·에디션·만료일 파싱
3. 우선순위: 사용자 지정 > 유효 라이선스 최신 버전 > MP > SE > BE/IC

``about`` 출력 형식 근거: 공개 저장소의 실제 Stata 로그(2차 자료, docs/IMPLEMENTATION_STATUS.md 참조).
일련번호·등록자는 로컬 doctor 화면에만 표시하고 AI 반환·점검 보고서에서는 제외함.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

EXE_RE = re.compile(r"^Stata(MP|SE|BE|IC)?-64\.exe$", re.IGNORECASE)
UNIX_EXE_NAMES = ("stata-mp", "stata-se", "stata", "stata-be")
_EDITION_RANK = {"MP": 3, "SE": 2, "BE": 1, "IC": 1}

_FIRST_LINE_RE = re.compile(
    r"^(?P<product>StataNow|Stata)(?:/(?P<edition>MP|SE|BE|IC))?\s+(?P<version>\d+(?:\.\d+)?)\s+for\s+(?P<platform>.+?)\s*$"
)
_REVISION_RE = re.compile(r"^Revision\s+(?P<rev>.+?)\s*$")
_LICENSE_RE = re.compile(r"^\s*Stata license:\s*(?P<lic>.+?)\s*$")
_EXPIRY_RE = re.compile(r"expiring\s+(?P<d>\d{1,2})\s+(?P<m>[A-Za-z]{3})\s+(?P<y>\d{4})")
_SERIAL_RE = re.compile(r"^\s*Serial number:\s*(?P<serial>\S+)")
_LICENSED_RE = re.compile(r"^\s*Licensed to:\s*(?P<who>.*?)\s*$")
_BATCH_REFUSED = "request ignored because of batch mode"


@dataclass
class AboutInfo:
    product: str | None = None  # "Stata" | "StataNow"
    edition: str | None = None  # MP | SE | BE | IC
    version: str | None = None  # "19.5"
    platform: str | None = None
    revision: str | None = None
    license_text: str | None = None
    perpetual: bool = False
    expires: date | None = None
    serial: str | None = None  # AI 반환 금지
    licensed_to: list[str] = field(default_factory=list)  # AI 반환 금지
    batch_refused: bool = False
    parsed: bool = False

    @property
    def major(self) -> int | None:
        if not self.version:
            return None
        return int(self.version.split(".")[0])

    def license_valid(self, today: date | None = None) -> bool | None:
        """True/False, 판단 불가 시 None."""
        if self.batch_refused:
            return False
        if self.perpetual:
            return True
        if self.expires:
            return self.expires >= (today or date.today())
        return None

    def public_dict(self, today: date | None = None) -> dict:
        """AI·보고서용(일련번호·등록자 제외)."""
        return {
            "product": self.product,
            "edition": self.edition,
            "version": self.version,
            "platform": self.platform,
            "revision": self.revision,
            "perpetual": self.perpetual,
            "expires": self.expires.isoformat() if self.expires else None,
            "license_valid": self.license_valid(today),
            "batch_refused": self.batch_refused,
        }


def parse_about(text: str) -> AboutInfo:
    info = AboutInfo()
    if _BATCH_REFUSED in text:
        info.batch_refused = True
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if line.startswith(". "):  # 명령 에코
            i += 1
            continue
        if info.version is None:
            m = _FIRST_LINE_RE.match(line)
            if m:
                info.product = m.group("product")
                info.edition = m.group("edition")
                info.version = m.group("version")
                info.platform = m.group("platform")
                info.parsed = True
                i += 1
                continue
        m = _REVISION_RE.match(line)
        if m and info.revision is None:
            info.revision = m.group("rev")
        m = _LICENSE_RE.match(raw)
        if m and info.license_text is None:
            lic = m.group("lic")
            info.license_text = lic
            info.perpetual = "perpetual" in lic.lower()
            em = _EXPIRY_RE.search(lic)
            if em:
                try:
                    info.expires = datetime.strptime(
                        f"{int(em.group('d')):02d} {em.group('m').title()} {em.group('y')}", "%d %b %Y"
                    ).date()
                except ValueError:
                    info.expires = None
        m = _SERIAL_RE.match(raw)
        if m and info.serial is None:
            info.serial = m.group("serial")
        m = _LICENSED_RE.match(raw)
        if m and not info.licensed_to:
            if m.group("who"):
                info.licensed_to.append(m.group("who"))
            j = i + 1
            # 등록자 둘째 줄 이후: 깊게 들여쓴 비어 있지 않은 줄
            while j < len(lines) and lines[j].startswith(" " * 10) and lines[j].strip():
                info.licensed_to.append(lines[j].strip())
                j += 1
            i = j
            continue
        i += 1
    return info


@dataclass
class StataInstall:
    exe: str
    edition_hint: str | None  # 실행파일명 기준
    version_hint: int | None  # 폴더명 기준
    source: str  # "scan" | "registry" | "user"
    about: AboutInfo | None = None
    about_error: str | None = None

    @property
    def edition(self) -> str | None:
        return (self.about.edition if self.about and self.about.edition else None) or self.edition_hint

    @property
    def version_number(self) -> float:
        if self.about and self.about.version:
            return float(self.about.version)
        return float(self.version_hint or 0)

    def license_valid(self, today: date | None = None) -> bool | None:
        return self.about.license_valid(today) if self.about else None

    def public_dict(self, today: date | None = None) -> dict:
        return {
            "exe": self.exe,
            "edition": self.edition,
            "version": self.about.version if self.about and self.about.version else self.version_hint,
            "source": self.source,
            "about": self.about.public_dict(today) if self.about else None,
            "about_error": self.about_error,
        }


def _edition_from_exe(name: str) -> str | None:
    m = EXE_RE.match(name)
    if m:
        return (m.group(1) or "IC").upper()
    low = name.lower()
    for ed in ("mp", "se", "be"):
        if low == f"stata-{ed}":
            return ed.upper()
    if low == "stata":
        return "BE"
    return None


def _version_from_path(path: str) -> int | None:
    for part in reversed(Path(path).parts[:-1]):
        m = re.search(r"Stata(?:Now)?\s*(\d{2})", part, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def windows_search_roots() -> list[str]:
    roots = ["C:\\"]
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(env)
        if v and v not in roots:
            roots.append(v)
    return roots


def scan_installations(roots: list[str] | None = None) -> list[StataInstall]:
    """경로 패턴 탐색. roots를 주면 Windows 규칙으로 해당 루트들만 탐색(테스트용)."""
    found: dict[str, StataInstall] = {}
    if roots is not None or IS_WINDOWS:
        for root in roots if roots is not None else windows_search_roots():
            for pattern in ("Stata*", "StataNow*"):
                for folder in glob.glob(os.path.join(root, pattern)):
                    if not os.path.isdir(folder):
                        continue
                    for entry in os.listdir(folder):
                        if EXE_RE.match(entry):
                            exe = os.path.join(folder, entry)
                            found.setdefault(os.path.normcase(exe), StataInstall(
                                exe, _edition_from_exe(entry), _version_from_path(exe), "scan"))
    else:
        patterns = [
            "/Applications/Stata*/Stata*.app/Contents/MacOS/stata*",
            "/Applications/Stata*/stata*",
            "/usr/local/stata*/stata*",
            "/opt/stata*/stata*",
        ]
        for pattern in patterns:
            for exe in glob.glob(pattern):
                name = os.path.basename(exe)
                if name in UNIX_EXE_NAMES and os.access(exe, os.X_OK):
                    found.setdefault(exe, StataInstall(exe, _edition_from_exe(name), _version_from_path(exe), "scan"))
    for inst in registry_installations():
        found.setdefault(os.path.normcase(inst.exe), inst)
    return list(found.values())


def _parse_server_command(value: str) -> str | None:
    value = value.strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        return value[1:end] if end > 0 else None
    m = re.match(r"^(.+?\.exe)\b", value, re.IGNORECASE)
    return m.group(1) if m else (value.split()[0] if value else None)


@dataclass
class ComRegistration:
    registered: bool
    server_path: str | None = None
    error: str | None = None


def com_registration(prog_id: str = "stata.StataOLEApp") -> ComRegistration:
    """레지스트리에서 COM 등록 경로 조회(HKCR\\ProgID\\CLSID → CLSID\\{..}\\LocalServer32)."""
    if not IS_WINDOWS:
        return ComRegistration(False, error="Windows 아님")
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\CLSID") as k:
            clsid, _ = winreg.QueryValueEx(k, "")
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32") as k:
            server, _ = winreg.QueryValueEx(k, "")
        return ComRegistration(True, _parse_server_command(server))
    except FileNotFoundError:
        return ComRegistration(False, error="COM 미등록(stata.StataOLEApp 키 없음)")
    except OSError as e:  # 권한 등
        return ComRegistration(False, error=str(e))


def registry_installations() -> list[StataInstall]:
    reg = com_registration()
    if reg.registered and reg.server_path and os.path.isfile(reg.server_path):
        name = os.path.basename(reg.server_path)
        return [StataInstall(reg.server_path, _edition_from_exe(name), _version_from_path(reg.server_path), "registry")]
    return []


def batch_command(exe: str, do_name: str) -> list[str]:
    """배치 실행 명령. Windows는 /e(완료 후 대기 없이 종료), Unix/Mac은 -b."""
    if IS_WINDOWS or exe.lower().endswith(".exe"):
        return [exe, "/e", "do", do_name]
    return [exe, "-b", "do", do_name]


def run_about(exe: str, timeout: int = 120) -> tuple[AboutInfo | None, str | None]:
    """``about``을 배치 실행해 파싱. (정보, 오류) 반환."""
    if not os.path.isfile(exe):
        return None, f"실행파일 없음: {exe}"
    with tempfile.TemporaryDirectory(prefix="stata_agent_about_") as tmp:
        do = Path(tmp) / "_sa_about.do"
        do.write_text("about\n", encoding="utf-8")
        try:
            subprocess.run(batch_command(exe, do.name), cwd=tmp, timeout=timeout,
                           capture_output=True, check=False)
        except subprocess.TimeoutExpired:
            return None, f"about 실행 시간 초과({timeout}초)"
        except OSError as e:
            return None, f"실행 실패: {e}"
        log = Path(tmp) / "_sa_about.log"
        if not log.is_file():
            return None, "배치 로그가 생성되지 않음(실행 권한·경로 확인)"
        info = parse_about(log.read_text(encoding="utf-8", errors="replace"))
        if not info.parsed and not info.batch_refused:
            return info, "about 출력 해석 실패(형식 변경 가능성)"
        return info, None


def choose_installation(installs: list[StataInstall], preferred_exe: str | None = None,
                        today: date | None = None) -> StataInstall | None:
    if not installs:
        return None
    if preferred_exe:
        for inst in installs:
            if os.path.normcase(inst.exe) == os.path.normcase(preferred_exe):
                return inst
    candidates = [i for i in installs if i.license_valid(today) is not False]
    if not candidates:
        return None

    def key(i: StataInstall):
        valid = i.license_valid(today)
        return (1 if valid else 0, i.version_number, _EDITION_RANK.get((i.edition or "").upper(), 0))

    return max(candidates, key=key)


def version_declaration(inst: StataInstall | None, fallback: int = 17) -> str:
    """do-file ``version`` 선언. StataNow 19.5도 주 버전(19)으로 선언(보수적 선택)."""
    if inst is None:
        return f"version {fallback}"
    if inst.about and inst.about.major:
        return f"version {inst.about.major}"
    if inst.version_hint:
        return f"version {inst.version_hint}"
    return f"version {fallback}"


@dataclass
class DiscoveryReport:
    installs: list[StataInstall]
    selected: StataInstall | None
    com: ComRegistration
    preferred_exe: str | None = None

    def public_dict(self) -> dict:
        return {
            "installs": [i.public_dict() for i in self.installs],
            "selected": self.selected.public_dict() if self.selected else None,
            "com_registered": self.com.registered,
            "com_server_path": self.com.server_path,
            "com_error": self.com.error,
            "preferred_exe": self.preferred_exe,
        }


def discover(run_about_checks: bool = True, preferred_exe: str | None = None) -> DiscoveryReport:
    preferred_exe = preferred_exe or os.environ.get("STATA_AGENT_STATA_EXE") or None
    installs = scan_installations()
    if preferred_exe and os.path.isfile(preferred_exe) and not any(
        os.path.normcase(i.exe) == os.path.normcase(preferred_exe) for i in installs
    ):
        name = os.path.basename(preferred_exe)
        installs.insert(0, StataInstall(preferred_exe, _edition_from_exe(name), _version_from_path(preferred_exe), "user"))
    if run_about_checks:
        for inst in installs:
            inst.about, inst.about_error = run_about(inst.exe)
    return DiscoveryReport(installs, choose_installation(installs, preferred_exe), com_registration(), preferred_exe)


__all__ = [
    "AboutInfo",
    "ComRegistration",
    "DiscoveryReport",
    "StataInstall",
    "batch_command",
    "choose_installation",
    "com_registration",
    "discover",
    "parse_about",
    "run_about",
    "scan_installations",
    "version_declaration",
]
