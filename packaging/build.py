"""배포 파일 빌드(설계서 Phase 5 단일 exe) — Windows에서 실행(GitHub Actions windows-latest).

산출물(--out, 기본 dist/) — 제품(stata·spss)별
- <제품>-agent-<버전>.exe   단일 실행파일(파이썬 설치 불필요). 더블클릭 = 설치 도우미, ``serve`` = MCP 서버
- THIRD_PARTY_NOTICES.txt   묶은 패키지의 사용권 고지(MIT 등은 고지 동봉 조건)

Claude 데스크톱 확장(.mcpb)은 2026-11-02 폐기(사용자 PC에서 열리지 않음, IMPLEMENTATION_STATUS §11.7)
→ Claude 앱 연결은 설치 도우미가 앱 설정에 직접 등록

사용
    python packaging/build.py                          # 두 제품 모두
    python packaging/build.py --product spss           # 한 제품만
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
from dataclasses import dataclass, field
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))

from stata_agent import __version__  # noqa: E402


@dataclass(frozen=True)
class Product:
    key: str                 # stata | spss
    name: str                # 실행파일 이름(stata-agent)
    entry: Path
    plugin: str
    skill: str
    package: str             # 묶을 파이썬 패키지
    hidden_imports: tuple = ()
    metadata: tuple = ("mcp",)
    win_hidden_imports: tuple = field(default=())

    @property
    def skill_dir(self) -> Path:
        return ROOT / "plugins" / self.plugin / "skills" / self.skill


STATA = Product(
    key="stata", name="stata-agent", entry=ROOT / "packaging" / "entry.py",
    plugin="stata-agent", skill="stata-analysis", package="stata_agent",
    hidden_imports=("stata_mcp.server",),
    metadata=("stata-gui-mcp", "mcp"),
    win_hidden_imports=("win32com.client", "pythoncom", "pywintypes"),
)

SPSS = Product(
    key="spss", name="spss-agent", entry=ROOT / "packaging" / "entry_spss.py",
    plugin="spss-agent", skill="spss-analysis", package="spss_agent",
)

PRODUCTS = {"stata": STATA, "spss": SPSS}


def third_party_notices() -> str:
    """빌드 환경에 설치된 배포 패키지의 이름·버전·사용권과 동봉 사용권 파일 본문."""
    parts = [
        "Stata·SPSS 에이전트 실행파일에 포함된 외부 패키지 사용권 고지",
        "(빌드 환경의 설치 정보로 자동 생성)",
        "",
    ]
    skip = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph",
            "pefile", "packaging", "pytest", "pluggy", "iniconfig", "pygments", "colorama"}
    for dist in sorted(md.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        name = dist.metadata["Name"] or "?"
        if name.lower() in skip or name.lower() == "stata-agent":
            continue
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        if len(lic) > 80:
            lic = lic.splitlines()[0][:80]
        parts.append("=" * 70)
        parts.append(f"{name} {dist.version}  사용권: {lic or '패키지 정보 참조'}")
        for f in dist.files or []:
            fname = f.name.upper()
            if fname.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                try:
                    parts.append("")
                    parts.append(Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip())
                except OSError:
                    pass
        parts.append("")
    # 실행파일에 포함된 파이썬 실행 환경 자체의 사용권(PSF)
    for cand in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if cand.is_file():
            parts += ["=" * 70, f"Python {sys.version.split()[0]}  사용권: PSF-2.0", "",
                      cand.read_text(encoding="utf-8", errors="replace").strip(), ""]
            break
    return "\n".join(parts) + "\n"


def build_exe(product: Product, out: Path, work: Path) -> Path:
    import PyInstaller.__main__  # 빌드 전용 의존

    win = sys.platform.startswith("win")
    sep = ";" if win else ":"
    args = [
        str(product.entry),
        "--onefile", "--console", "--noconfirm", "--clean",
        "--name", product.name,
        "--paths", str(ROOT / "mcp_server"),
        "--add-data", f"{product.skill_dir}{sep}skills/{product.skill}",
        "--collect-submodules", product.package,
    ]
    for mod in product.hidden_imports + (product.win_hidden_imports if win else ()):
        args += ["--hidden-import", mod]
    for dist in product.metadata:  # 버전 확인(importlib.metadata)용 배포 정보 동봉
        args += ["--copy-metadata", dist]
    args += ["--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work)]
    PyInstaller.__main__.run(args)
    suffix = ".exe" if win else ""
    built = work / "dist" / f"{product.name}{suffix}"
    dest = out / f"{product.name}-{__version__}{suffix}"
    shutil.copy2(built, dest)
    return dest


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows CI 파이프 출력(cp1252)에서 한글 오류 방지
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="실행파일 빌드")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--product", choices=("all", "stata", "spss"), default="all")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    products = list(PRODUCTS.values()) if args.product == "all" else [PRODUCTS[args.product]]
    (out / "THIRD_PARTY_NOTICES.txt").write_text(third_party_notices(), encoding="utf-8")
    for prod in products:
        exe = build_exe(prod, out, out / "_work" / prod.key)
        print(f"[{prod.key}] 실행파일: {exe}")


if __name__ == "__main__":
    main()
