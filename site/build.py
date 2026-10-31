"""설명서 사이트 빌드(설계서 §0.6 온라인 안내 사이트) → GitHub Pages 배포용 ``_site/``.

- ``site/index.html``의 자리표시자({{VERSION}} 등)를 채움
- 페이지: index.html(Stata)·spss.html(SPSS), 공용 스타일 style.css
- 분석 스킬 ZIP 생성(Stata·SPSS): Claude 앱 업로드 규격에 맞춰 ZIP 최상위에 스킬 폴더
  (Claude 공식 안내: "Upload a ZIP file containing your skill folder")
- 같은 내용이면 같은 확인값(SHA-256)이 나오도록 ZIP 항목 순서·시각 고정
- --binaries: Windows 빌드 산출물(실행파일·.mcpb·사용권 고지)을 downloads/에 넣고 확인값·
  ``latest.json``(Claude Code 설치 명령 /stata-agent:setup이 읽는 배포 정보) 생성.
  없으면(로컬 미리보기) 내려받기 버튼을 '배포 빌드에서 생성'으로 표시

사용: python site/build.py [--out _site] [--binaries 폴더]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = ROOT / "site"
SKILL_DIR = ROOT / "plugins" / "stata-agent" / "skills" / "stata-analysis"
SPSS_SKILL_DIR = ROOT / "plugins" / "spss-agent" / "skills" / "spss-analysis"
PAGES = ("index.html", "spss.html")
ASSETS = ("style.css",)
VERSION_FILE = ROOT / "mcp_server" / "stata_agent" / "__init__.py"
REPO_URL = "https://github.com/beaver21c/stata_connect"
SITE_URL = "https://beaver21c.github.io/stata_connect/"
PENDING = "배포 빌드에서 생성"
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_EXCLUDE = {"__pycache__", ".DS_Store"}


def read_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("버전 정보를 찾지 못함: " + str(VERSION_FILE))
    return m.group(1)


def build_skill_zip(dest: Path, skill_dir: Path = SKILL_DIR) -> Path:
    files = sorted(
        p for p in skill_dir.rglob("*")
        if p.is_file() and not any(part in _EXCLUDE for part in p.parts)
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            arc = f"{skill_dir.name}/{p.relative_to(skill_dir).as_posix()}"
            info = zipfile.ZipInfo(arc, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, p.read_bytes())
    return dest


def human_size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _zip_values(prefix: str, skill_dir: Path, version: str, downloads: Path) -> tuple[dict, str]:
    zip_name = f"{skill_dir.name}-{version}.zip"
    data = build_skill_zip(downloads / zip_name, skill_dir).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    return ({f"{prefix}SKILL_ZIP": zip_name, f"{prefix}SKILL_SIZE": human_size(len(data)),
             f"{prefix}SKILL_SHA256": sha}, f"{sha}  {zip_name}\n")


def _binary_values(prefix: str, name: str, binaries: Path | None, downloads: Path) -> tuple[dict, str, dict | None]:
    """실행파일·.mcpb 한 개의 자리표시자 값, SHA256SUMS 줄, latest.json 항목."""
    src = binaries / name if binaries else None
    if src is None or not src.is_file():
        button = f'<a class="btn" aria-disabled="true" role="link" tabindex="-1">{PENDING}</a>'
        return ({f"{prefix}_FILE": name, f"{prefix}_BUTTON": button, f"{prefix}_SHA256": PENDING}, "", None)
    data = src.read_bytes()
    shutil.copy2(src, downloads / name)
    sha = hashlib.sha256(data).hexdigest()
    button = f'<a class="btn" href="downloads/{name}" download>받기 ({human_size(len(data))})</a>'
    entry = {"file": name, "url": f"{SITE_URL}downloads/{name}", "sha256": sha, "size": len(data)}
    return ({f"{prefix}_FILE": name, f"{prefix}_BUTTON": button, f"{prefix}_SHA256": sha}, f"{sha}  {name}\n", entry)


def build(out: Path, binaries: Path | None = None) -> dict:
    version = read_version()
    if out.exists():
        shutil.rmtree(out)
    downloads = out / "downloads"
    stata_vals, stata_sum = _zip_values("", SKILL_DIR, version, downloads)
    spss_vals, spss_sum = _zip_values("SPSS_", SPSS_SKILL_DIR, version, downloads)
    exe_vals, exe_sum, exe_entry = _binary_values("EXE", f"stata-agent-{version}.exe", binaries, downloads)
    mcpb_vals, mcpb_sum, mcpb_entry = _binary_values("MCPB", f"stata-agent-{version}.mcpb", binaries, downloads)
    s_exe_vals, s_exe_sum, s_exe_entry = _binary_values("SPSS_EXE", f"spss-agent-{version}.exe", binaries, downloads)
    s_mcpb_vals, s_mcpb_sum, s_mcpb_entry = _binary_values("SPSS_MCPB", f"spss-agent-{version}.mcpb", binaries,
                                                           downloads)
    (downloads / "SHA256SUMS.txt").write_text(stata_sum + spss_sum + exe_sum + mcpb_sum + s_exe_sum + s_mcpb_sum,
                                              encoding="utf-8")
    notices = binaries / "THIRD_PARTY_NOTICES.txt" if binaries else None
    if notices is not None and notices.is_file():
        shutil.copy2(notices, downloads / "THIRD_PARTY_NOTICES.txt")
    else:
        (downloads / "THIRD_PARTY_NOTICES.txt").write_text(f"{PENDING}(실행파일에 포함된 외부 구성요소 사용권 고지)\n",
                                                           encoding="utf-8")
    if exe_entry:
        # 최상위 exe·mcpb = Stata(기존 /stata-agent:setup 호환), spss 항목 = SPSS판(/spss-agent:setup)
        latest = {"version": version, "exe": exe_entry, "mcpb": mcpb_entry,
                  "skill_zip": f"{SITE_URL}downloads/{stata_vals['SKILL_ZIP']}"}
        if s_exe_entry:
            latest["spss"] = {"exe": s_exe_entry, "mcpb": s_mcpb_entry,
                              "skill_zip": f"{SITE_URL}downloads/{spss_vals['SPSS_SKILL_ZIP']}"}
        (downloads / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")

    values = {
        "VERSION": version,
        **stata_vals,
        **spss_vals,
        **exe_vals,
        **mcpb_vals,
        **s_exe_vals,
        **s_mcpb_vals,
        "BUILD_DATE": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "REPO_URL": REPO_URL,
    }
    for page in PAGES:
        html = (SITE_SRC / page).read_text(encoding="utf-8")
        for key, value in values.items():
            html = html.replace("{{" + key + "}}", value)
        leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
        if leftover:
            raise SystemExit(f"{page}: 채우지 못한 자리표시자 {sorted(set(leftover))}")
        (out / page).write_text(html, encoding="utf-8")
    for asset in ASSETS:
        shutil.copy2(SITE_SRC / asset, out / asset)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="설명서 사이트 빌드")
    parser.add_argument("--out", default=str(ROOT / "_site"))
    parser.add_argument("--binaries", help="Windows 빌드 산출물 폴더(실행파일·.mcpb·사용권 고지)")
    args = parser.parse_args()
    values = build(Path(args.out), Path(args.binaries) if args.binaries else None)
    print(f"빌드 완료: {args.out} (v{values['VERSION']}, {values['SKILL_ZIP']} {values['SKILL_SIZE']}, "
          f"{values['SPSS_SKILL_ZIP']} {values['SPSS_SKILL_SIZE']}, 실행파일 "
          f"{'포함' if values['EXE_SHA256'] != PENDING else '없음'})")


if __name__ == "__main__":
    main()
