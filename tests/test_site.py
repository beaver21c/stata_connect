"""설명서 사이트 빌드(site/build.py) 검사."""

import importlib.util
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_build():
    spec = importlib.util.spec_from_file_location("site_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_outputs(tmp_path):
    build = _load_build()
    values = build.build(tmp_path / "_site")
    html = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert "{{" not in html
    assert f"v{values['VERSION']}" in html and values["SKILL_SHA256"] in html

    # 다운로드 링크가 실제 파일을 가리킴
    for href in re.findall(r'href="(downloads/[^"]+)"', html):
        assert (tmp_path / "_site" / href).is_file(), href

    # 페이지 안 이동 링크(#id)마다 대상이 있음
    ids = set(re.findall(r'id="([^"]+)"', html))
    for anchor in set(re.findall(r'href="#([^"]+)"', html)):
        assert anchor in ids, anchor


def test_skill_zip_matches_claude_upload_rules(tmp_path):
    """Claude 앱 업로드: ZIP 안에 스킬 폴더(이름 = SKILL.md의 name)가 최상위로 있어야 함."""
    build = _load_build()
    z = build.build_skill_zip(tmp_path / "s.zip")
    names = zipfile.ZipFile(z).namelist()
    assert "stata-analysis/SKILL.md" in names
    assert all(n.startswith("stata-analysis/") for n in names)
    assert not any("__pycache__" in n for n in names)


def test_skill_zip_is_reproducible(tmp_path):
    build = _load_build()
    a = build.build_skill_zip(tmp_path / "a.zip").read_bytes()
    b = build.build_skill_zip(tmp_path / "b.zip").read_bytes()
    assert a == b
