"""배포 파일 빌드(설계서 Phase 5 단일 exe·.mcpb) — Windows에서 실행(GitHub Actions windows-latest).

산출물(--out, 기본 dist/) — 제품(stata·spss)별
- <제품>-agent-<버전>.exe   단일 실행파일(파이썬 설치 불필요). 더블클릭 = 설치 도우미, ``serve`` = MCP 서버
- <제품>-agent-<버전>.mcpb  Claude 데스크톱 앱 확장(더블클릭 → 설치 화면). 위 실행파일 + manifest.json
- THIRD_PARTY_NOTICES.txt   묶은 패키지의 사용권 고지(MIT 등은 고지 동봉 조건)

사용
    python packaging/build.py                          # 두 제품 모두
    python packaging/build.py --product spss           # 한 제품만
    python packaging/build.py --product stata --exe 경로   # 이미 만든 실행파일로 .mcpb만 구성
    python packaging/build.py --manifest-only --out 폴더   # manifest-<제품>.json만(검사용)

.mcpb 압축: 공식 CLI(``npx @anthropic-ai/mcpb pack``)가 있으면 사용, 없으면 zip으로 직접 구성
(MCPB 공식 설명: manifest.json을 포함한 zip 묶음).
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
from dataclasses import dataclass, field
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))

from spss_agent.tool_specs import TOOLS as SPSS_TOOLS  # noqa: E402
from stata_agent import __version__  # noqa: E402
from stata_agent.tool_specs import TOOLS as STATA_TOOLS  # noqa: E402

SITE_URL = "https://beaver21c.github.io/stata_connect/"
REPO_URL = "https://github.com/beaver21c/stata_connect"
MCPB_CLI = "@anthropic-ai/mcpb@2.1.2"


@dataclass(frozen=True)
class Product:
    key: str                 # stata | spss
    name: str                # 실행파일·확장 이름(stata-agent)
    display: str
    entry: Path
    plugin: str
    skill: str
    package: str             # 묶을 파이썬 패키지
    tools: tuple
    description: str
    long_description: str
    keywords: tuple
    env: dict
    user_config: dict
    doc_url: str
    hidden_imports: tuple = ()
    metadata: tuple = ("mcp",)
    win_hidden_imports: tuple = field(default=())

    @property
    def exe_in_bundle(self) -> str:
        return f"server/{self.name}.exe"

    @property
    def skill_dir(self) -> Path:
        return ROOT / "plugins" / self.plugin / "skills" / self.skill


STATA = Product(
    key="stata", name="stata-agent", display="Stata 에이전트", entry=ROOT / "packaging" / "entry.py",
    plugin="stata-agent", skill="stata-analysis", package="stata_agent", tools=STATA_TOOLS,
    description="Stata가 계산하고 AI는 do-file 작성·결과 판독을 맡는 분석 도구(원자료 행은 AI로 보내지 않음)",
    long_description=(
        "채팅으로 요청하면 AI가 do-file을 섹션 단위로 작성·수정하고, 계산은 이 PC의 Stata가 수행함. "
        "원자료 행을 보여 주는 명령은 실행 전에 차단하고, 출력도 한 번 더 걸러서 AI에 전달함. "
        "Stata 17 이상(Windows)용. 분석 방법 안내는 함께 제공하는 stata-analysis 스킬을 설치해야 완전하게 동작함. "
        "설명서: " + SITE_URL
    ),
    keywords=("stata", "statistics", "research", "do-file"),
    env={"STATA_AGENT_STATA_EXE": "${user_config.stata_exe}",
         "STATA_AGENT_MASK_SMALL_CELLS": "${user_config.mask_small_cells}"},
    user_config={
        "stata_exe": {
            "type": "file",
            "title": "Stata 실행파일(선택)",
            "description": "비워 두면 자동으로 찾음. 여러 버전이 있거나 찾지 못할 때만 지정(예: C:\\Program Files\\Stata18\\StataSE-64.exe)",
            "required": False,
        },
        "mask_small_cells": {
            "type": "number",
            "title": "빈도표 소표본 가림 기준",
            "description": "빈도표에서 이 값보다 작은 칸을 가림(0=끔, 예: 5)",
            "required": False,
            "default": 0,
            "min": 0,
            "max": 100,
        },
    },
    doc_url=SITE_URL,
    hidden_imports=("stata_mcp.server",),
    metadata=("stata-gui-mcp", "mcp"),
    win_hidden_imports=("win32com.client", "pythoncom", "pywintypes"),
)

SPSS = Product(
    key="spss", name="spss-agent", display="SPSS 에이전트", entry=ROOT / "packaging" / "entry_spss.py",
    plugin="spss-agent", skill="spss-analysis", package="spss_agent", tools=SPSS_TOOLS,
    description="SPSS가 계산하고 AI는 문법(.sps) 작성·결과 판독을 맡는 분석 도구(원자료 사례 값은 AI로 보내지 않음)",
    long_description=(
        "채팅으로 요청하면 AI가 SPSS 문법을 섹션 단위로 작성·수정하고, 계산은 이 PC의 SPSS Statistics가 화면 없이 수행함. "
        "사례 값을 보여 주는 명령은 실행 전에 차단하고, 출력도 한 번 더 걸러서 AI에 전달함. "
        "SPSS Statistics 22 이상(Windows, 동봉 Python 필요)용. 분석 방법 안내는 spss-analysis 스킬을 함께 설치해야 함. "
        "설명서: " + SITE_URL + "spss.html"
    ),
    keywords=("spss", "statistics", "research", "syntax"),
    env={"SPSS_AGENT_HOME": "${user_config.spss_home}", "SPSS_AGENT_PYTHON": "${user_config.spss_python}"},
    user_config={
        "spss_home": {
            "type": "directory",
            "title": "SPSS 설치 폴더(선택)",
            "description": "비워 두면 자동으로 찾음. 찾지 못하거나 여러 버전일 때만 stats.exe가 있는 폴더 지정"
                           "(예: C:\\Program Files\\IBM\\SPSS Statistics\\27)",
            "required": False,
        },
        "spss_python": {
            "type": "file",
            "title": "SPSS 동봉 Python(선택)",
            "description": "비워 두면 설치 폴더의 Python3 또는 Python(22~26의 2.7)에서 찾음. 다른 위치일 때만 python.exe 지정",
            "required": False,
        },
    },
    doc_url=SITE_URL + "spss.html",
)

PRODUCTS = {"stata": STATA, "spss": SPSS}


def manifest(product: Product = STATA, version: str = __version__) -> dict:
    """MCPB manifest v0.3(공식 스키마 mcpb-manifest-v0.3.schema.json 필드만 사용)."""
    env = dict(product.env)
    return {
        "manifest_version": "0.3",
        "name": product.name,
        "display_name": product.display,
        "version": version,
        "description": product.description,
        "long_description": product.long_description,
        "author": {"name": "beaver21c", "url": "https://github.com/beaver21c"},
        "repository": {"type": "git", "url": REPO_URL},
        "homepage": product.doc_url,
        "documentation": product.doc_url,
        "support": REPO_URL + "/issues",
        "server": {
            "type": "binary",
            "entry_point": product.exe_in_bundle,
            "mcp_config": {
                "command": f"${{__dirname}}/server/{product.name}",
                "args": ["serve"],
                "env": env,
                # 공식 예시: win32 재정의에서 .exe를 명시
                "platform_overrides": {
                    "win32": {"command": "${__dirname}/" + product.exe_in_bundle, "args": ["serve"], "env": env},
                },
            },
        },
        "tools": [{"name": t.name, "description": t.description} for t in product.tools],
        "keywords": list(product.keywords),
        "compatibility": {"platforms": ["win32"]},
        "user_config": product.user_config,
    }


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


def stage_mcpb(product: Product, exe: Path, stage: Path, notices: str) -> Path:
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "server").mkdir(parents=True)
    shutil.copy2(exe, stage / product.exe_in_bundle)
    (stage / "manifest.json").write_text(json.dumps(manifest(product), ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    (stage / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")
    return stage


def pack_mcpb(stage: Path, dest: Path) -> Path:
    npx = shutil.which("npx")
    if npx:
        r = subprocess.run([npx, "-y", MCPB_CLI, "pack", str(stage), str(dest)], check=False)
        if r.returncode == 0 and dest.is_file():
            return dest
        print("공식 CLI 압축 실패 → zip으로 직접 구성", file=sys.stderr)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(stage).as_posix())
    return dest


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows CI 파이프 출력(cp1252)에서 한글 오류 방지
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="실행파일·.mcpb 빌드")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--product", choices=("all", "stata", "spss"), default="all")
    ap.add_argument("--exe", help="이미 빌드한 실행파일(--product 하나와 함께, 지정 시 PyInstaller 생략)")
    ap.add_argument("--manifest-only", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    products = list(PRODUCTS.values()) if args.product == "all" else [PRODUCTS[args.product]]
    if args.exe and len(products) != 1:
        raise SystemExit("--exe는 --product stata 또는 spss와 함께 사용")
    if args.manifest_only:
        for prod in products:
            path = out / f"manifest-{prod.key}.json"
            path.write_text(json.dumps(manifest(prod), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(path)
        return
    notices = third_party_notices()
    (out / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")
    for prod in products:
        work = out / "_work" / prod.key
        exe = Path(args.exe) if args.exe else build_exe(prod, out, work)
        stage = stage_mcpb(prod, exe, work / "mcpb", notices)
        mcpb = pack_mcpb(stage, out / f"{prod.name}-{__version__}.mcpb")
        print(f"[{prod.key}] 실행파일: {exe}\n[{prod.key}] 확장: {mcpb}")


if __name__ == "__main__":
    main()
