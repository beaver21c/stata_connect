import re
from pathlib import Path

from stata_agent.project import init_project, rendered_templates
from stata_agent.tool_specs import TOOLS

SKILL_DIR = Path(__file__).resolve().parents[1] / "plugins" / "stata-agent" / "skills" / "stata-analysis"


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "SKILL.md frontmatter 없음"
    fields = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_skill_frontmatter_meets_app_upload_rules():
    """Claude 앱 업로드 규칙: name 소문자·숫자·하이픈 64자 이내·폴더명 일치, description 1,024자 이내,
    허용 필드만 사용(name, description, license, compatibility, metadata, allowed-tools)."""
    fm = _frontmatter((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
    assert set(fm) <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fm["name"]) and fm["name"] == SKILL_DIR.name
    assert 0 < len(fm["description"]) <= 1024


def test_skill_mentions_every_tool():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for t in TOOLS:
        assert t.name in text, t.name


def test_references_exist():
    for name in ("descriptive", "ttest", "anova", "correlation", "regression", "sem", "panel", "nonlinear", "reporting"):
        assert (SKILL_DIR / "references" / f"{name}.md").is_file()


def test_templates_in_sync_with_code():
    for name, content in rendered_templates().items():
        assert (SKILL_DIR / "templates" / name).read_text(encoding="utf-8") == content, \
            f"{name} 불일치 → `stata-agent render-templates` 실행"


def test_init_project_is_non_destructive(tmp_path):
    (tmp_path / "AGENTS.md").write_text("내 지침", encoding="utf-8")
    created = init_project(tmp_path, "version 18", example=True)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "내 지침"
    assert "01_describe.do" in created and "AGENTS.md" not in created
    assert init_project(tmp_path, "version 18", example=True) == []
