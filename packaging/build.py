"""배포 파일 빌드(설계서 Phase 5 단일 exe·.mcpb) — Windows에서 실행(GitHub Actions windows-latest).

산출물(--out, 기본 dist/)
- stata-agent-<버전>.exe   단일 실행파일(파이썬 설치 불필요). 더블클릭 = 설치 도우미, ``serve`` = MCP 서버
- stata-agent-<버전>.mcpb  Claude 데스크톱 앱 확장(더블클릭 → 설치 화면). 위 실행파일 + manifest.json
- THIRD_PARTY_NOTICES.txt  묶은 패키지의 사용권 고지(MIT 등은 고지 동봉 조건)

사용
    python packaging/build.py                # 실행파일 + .mcpb
    python packaging/build.py --exe 경로     # 이미 만든 실행파일로 .mcpb만 구성
    python packaging/build.py --manifest-only --out 폴더   # manifest.json만(검사용)

.mcpb 압축: 공식 CLI(``npx @anthropic-ai/mcpb pack``)가 있으면 사용, 없으면 zip으로 직접 구성
(MCPB 공식 설명: manifest.json을 포함한 zip 묶음).
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))

from stata_agent import __version__  # noqa: E402
from stata_agent.tool_specs import TOOLS  # noqa: E402

ENTRY = ROOT / "packaging" / "entry.py"
SKILL_DIR = ROOT / "plugins" / "stata-agent" / "skills" / "stata-analysis"
SITE_URL = "https://beaver21c.github.io/stata_connect/"
REPO_URL = "https://github.com/beaver21c/stata_connect"
EXE_IN_BUNDLE = "server/stata-agent.exe"
MCPB_CLI = "@anthropic-ai/mcpb@2.1.2"


def manifest(version: str = __version__) -> dict:
    """MCPB manifest v0.3(공식 스키마 mcpb-manifest-v0.3.schema.json 필드만 사용)."""
    env = {
        "STATA_AGENT_STATA_EXE": "${user_config.stata_exe}",
        "STATA_AGENT_MASK_SMALL_CELLS": "${user_config.mask_small_cells}",
    }
    return {
        "manifest_version": "0.3",
        "name": "stata-agent",
        "display_name": "Stata 에이전트",
        "version": version,
        "description": "Stata가 계산하고 AI는 do-file 작성·결과 판독을 맡는 분석 도구(원자료 행은 AI로 보내지 않음)",
        "long_description": (
            "채팅으로 요청하면 AI가 do-file을 섹션 단위로 작성·수정하고, 계산은 이 PC의 Stata가 수행함. "
            "원자료 행을 보여 주는 명령은 실행 전에 차단하고, 출력도 한 번 더 걸러서 AI에 전달함. "
            "Stata 17 이상(Windows)용. 분석 방법 안내는 함께 제공하는 stata-analysis 스킬을 설치해야 완전하게 동작함. "
            "설명서: " + SITE_URL
        ),
        "author": {"name": "beaver21c", "url": "https://github.com/beaver21c"},
        "repository": {"type": "git", "url": REPO_URL},
        "homepage": SITE_URL,
        "documentation": SITE_URL,
        "support": REPO_URL + "/issues",
        "server": {
            "type": "binary",
            "entry_point": EXE_IN_BUNDLE,
            "mcp_config": {
                "command": "${__dirname}/server/stata-agent",
                "args": ["serve"],
                "env": env,
                # 공식 예시: win32 재정의에서 .exe를 명시
                "platform_overrides": {
                    "win32": {"command": "${__dirname}/" + EXE_IN_BUNDLE, "args": ["serve"], "env": env},
                },
            },
        },
        "tools": [{"name": t.name, "description": t.description} for t in TOOLS],
        "keywords": ["stata", "statistics", "research", "do-file"],
        "compatibility": {"platforms": ["win32"]},
        "user_config": {
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
    }


def third_party_notices() -> str:
    """빌드 환경에 설치된 배포 패키지의 이름·버전·사용권과 동봉 사용권 파일 본문."""
    parts = [
        "Stata 에이전트 실행파일에 포함된 외부 패키지 사용권 고지",
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


def build_exe(out: Path, work: Path) -> Path:
    import PyInstaller.__main__  # 빌드 전용 의존

    sep = ";" if sys.platform.startswith("win") else ":"
    PyInstaller.__main__.run([
        str(ENTRY),
        "--onefile", "--console", "--noconfirm", "--clean",
        "--name", "stata-agent",
        "--paths", str(ROOT / "mcp_server"),
        "--add-data", f"{SKILL_DIR}{sep}skills/stata-analysis",
        "--collect-submodules", "stata_agent",
        "--hidden-import", "stata_mcp.server",
        *(["--hidden-import", "win32com.client", "--hidden-import", "pythoncom", "--hidden-import", "pywintypes"]
          if sys.platform.startswith("win") else []),
        # 버전 확인(importlib.metadata)용 배포 정보 동봉
        "--copy-metadata", "stata-gui-mcp",
        "--copy-metadata", "mcp",
        "--distpath", str(work / "dist"),
        "--workpath", str(work / "build"),
        "--specpath", str(work),
    ])
    suffix = ".exe" if sys.platform.startswith("win") else ""
    built = work / "dist" / f"stata-agent{suffix}"
    dest = out / f"stata-agent-{__version__}{suffix}"
    shutil.copy2(built, dest)
    return dest


def stage_mcpb(exe: Path, stage: Path, notices: str) -> Path:
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "server").mkdir(parents=True)
    shutil.copy2(exe, stage / EXE_IN_BUNDLE)
    (stage / "manifest.json").write_text(json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    ap.add_argument("--exe", help="이미 빌드한 실행파일(지정 시 PyInstaller 생략)")
    ap.add_argument("--manifest-only", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.manifest_only:
        (out / "manifest.json").write_text(json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(out / "manifest.json")
        return
    work = out / "_work"
    exe = Path(args.exe) if args.exe else build_exe(out, work)
    notices = third_party_notices()
    (out / "THIRD_PARTY_NOTICES.txt").write_text(notices, encoding="utf-8")
    stage = stage_mcpb(exe, work / "mcpb", notices)
    mcpb = pack_mcpb(stage, out / f"stata-agent-{__version__}.mcpb")
    print(f"실행파일: {exe}\n확장: {mcpb}")


if __name__ == "__main__":
    main()
