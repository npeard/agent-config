"""Contract tests for the portable Agent Skills profile."""

from pathlib import Path

import validate_skills

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_skill(root: Path, directory: str, frontmatter: str) -> Path:
    path = root / directory / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n# Skill\n", encoding="utf-8")
    return path


def details(path: Path) -> list[str]:
    return [finding.detail for finding in validate_skills.validate_skill(path)]


def test_repository_skills_conform_to_the_portable_profile():
    assert validate_skills.validate(REPO_ROOT / "skills") == []


def test_name_must_match_its_directory(tmp_path):
    path = write_skill(
        tmp_path, "right-name", "name: wrong-name\ndescription: Use when testing."
    )
    assert any("does not match directory" in detail for detail in details(path))


def test_name_uses_the_open_standard_character_set(tmp_path):
    path = write_skill(
        tmp_path, "Bad_Name", "name: Bad_Name\ndescription: Use when testing."
    )
    assert any("lowercase letters" in detail for detail in details(path))


def test_description_may_be_a_multiline_block_scalar(tmp_path):
    path = write_skill(
        tmp_path,
        "multiline",
        "name: multiline\ndescription: |-\n  Use when a description\n  spans lines.",
    )
    assert details(path) == []


def test_required_fields_are_non_empty(tmp_path):
    path = write_skill(tmp_path, "empty", "name: empty\ndescription:")
    assert "missing non-empty 'description'" in details(path)


def test_standard_length_limits_are_enforced(tmp_path):
    path = write_skill(
        tmp_path,
        "long",
        f"name: long\ndescription: {'x' * 1025}\ncompatibility: {'y' * 501}",
    )
    found = details(path)
    assert any("description is 1025 characters" in detail for detail in found)
    assert any("compatibility is 501 characters" in detail for detail in found)


def test_non_standard_top_level_fields_are_rejected(tmp_path):
    path = write_skill(
        tmp_path,
        "extended",
        "name: extended\ndescription: Use when testing.\nhost-magic: enabled",
    )
    assert "non-standard frontmatter field 'host-magic'" in details(path)


def test_every_immediate_directory_must_be_a_skill(tmp_path):
    (tmp_path / "missing").mkdir()
    found = validate_skills.validate(tmp_path)
    assert [finding.detail for finding in found] == [
        "every skill directory must contain SKILL.md"
    ]
