"""설명서 사이트 빌드(설계서 §0.6 온라인 안내 사이트) → GitHub Pages 배포용 ``_site/``.

- ``site/index.html``의 자리표시자({{VERSION}} 등)를 채움
- 분석 스킬 ZIP 생성: Claude 앱 업로드 규격에 맞춰 ZIP 최상위에 ``stata-analysis/`` 폴더
  (Claude 공식 안내: "Upload a ZIP file containing your skill folder")
- 같은 내용이면 같은 확인값(SHA-256)이 나오도록 ZIP 항목 순서·시각 고정

사용: python site/build.py [--out _site]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = ROOT / "site"
SKILL_DIR = ROOT / "skills" / "stata-analysis"
VERSION_FILE = ROOT / "mcp_server" / "stata_agent" / "__init__.py"
REPO_URL = "https://github.com/beaver21c/stata_connect"
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


def build(out: Path) -> dict:
    version = read_version()
    if out.exists():
        shutil.rmtree(out)
    downloads = out / "downloads"
    zip_name = f"stata-analysis-{version}.zip"
    zip_path = build_skill_zip(downloads / zip_name)
    data = zip_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    (downloads / "SHA256SUMS.txt").write_text(f"{sha}  {zip_name}\n", encoding="utf-8")

    values = {
        "VERSION": version,
        "SKILL_ZIP": zip_name,
        "SKILL_SIZE": human_size(len(data)),
        "SKILL_SHA256": sha,
        "BUILD_DATE": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "REPO_URL": REPO_URL,
    }
    html = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    for key, value in values.items():
        html = html.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if leftover:
        raise SystemExit(f"채우지 못한 자리표시자: {sorted(set(leftover))}")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="설명서 사이트 빌드")
    parser.add_argument("--out", default=str(ROOT / "_site"))
    args = parser.parse_args()
    values = build(Path(args.out))
    print(f"빌드 완료: {args.out} (v{values['VERSION']}, {values['SKILL_ZIP']} {values['SKILL_SIZE']})")


if __name__ == "__main__":
    main()
