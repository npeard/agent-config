"""Tests for scripts/audit_assets.py.

Each check gets a fixture that violates it and one that does not, because a
check that fires on everything and a check that fires on nothing both pass a
single-fixture test.

The baseline tests are the success metric made executable: the spec measured
nine findings on the tree as it stood, and those tests are what make "fixed
or ledgered" checkable rather than asserted.
"""

from __future__ import annotations

from pathlib import Path

import audit_assets
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CLEAN_BODY = "# Body\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"


def write_skill(
    root: Path, name: str, description: str, body: str = CLEAN_BODY
) -> Path:
    d = root / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    path = d / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}")
    return path


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    """A minimal repo shaped like claude-config, with nothing wrong in it."""
    (tmp_path / "skills").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "hooks").mkdir()
    (tmp_path / "CLAUDE.md").write_text("word " * 10)
    (tmp_path / "pixi.toml").write_text('[tasks]\nfmt = "true"\n')
    write_skill(tmp_path, "alpha", "Use when you need alpha")
    return tmp_path


class TestTriggerShaped:
    def test_description_not_leading_with_a_trigger_is_reported(self, fake_root):
        write_skill(
            fake_root, "beta", "Rewrite text so it reads better. Use when editing"
        )
        found = audit_assets.check_trigger_shaped(fake_root)
        assert [f.asset for f in found] == ["skills/beta/SKILL.md"]
        assert found[0].principle == 1
        assert "Rewrite text" in found[0].detail

    def test_description_leading_with_a_trigger_is_silent(self, fake_root):
        write_skill(fake_root, "beta", "Use when editing prose for stock phrasing")
        assert audit_assets.check_trigger_shaped(fake_root) == []

    def test_every_opener_in_the_constant_is_accepted(self, fake_root):
        for i, opener in enumerate(audit_assets.TRIGGER_OPENERS):
            write_skill(fake_root, f"s{i}", f"{opener} something happens")
        assert audit_assets.check_trigger_shaped(fake_root) == []

    def test_missing_description_is_reported(self, fake_root):
        (fake_root / "skills" / "gamma").mkdir()
        (fake_root / "skills" / "gamma" / "SKILL.md").write_text("# No frontmatter\n")
        found = audit_assets.check_trigger_shaped(fake_root)
        assert "no description" in found[0].detail

    def test_trigger_clause_is_the_first_clause_not_the_whole_string(self, fake_root):
        """A trigger buried after a leading sentence still fails: the
        description is read top-down and the first clause is what decides."""
        write_skill(fake_root, "beta", "Formats things, use when formatting")
        assert audit_assets.check_trigger_shaped(fake_root)


class TestBudgets:
    def test_oversized_claude_md_is_reported(self, fake_root):
        (fake_root / "CLAUDE.md").write_text(
            "word " * (audit_assets.CLAUDE_MD_MAX_WORDS + 1)
        )
        found = audit_assets.check_budgets(fake_root)
        assert [f.asset for f in found] == ["CLAUDE.md"]
        assert found[0].principle == 3

    def test_oversized_skill_body_is_reported(self, fake_root):
        write_skill(
            fake_root,
            "big",
            "Use when big",
            "word " * (audit_assets.SKILL_BODY_MAX_WORDS + 1),
        )
        assert any(
            f.asset == "skills/big/SKILL.md"
            for f in audit_assets.check_budgets(fake_root)
        )

    def test_oversized_description_is_reported(self, fake_root):
        long = "Use when " + "x " * (audit_assets.SKILL_DESCRIPTION_MAX_WORDS + 1)
        write_skill(fake_root, "verbose", long)
        found = audit_assets.check_budgets(fake_root)
        assert any("description" in f.detail for f in found)

    def test_clean_tree_is_silent(self, fake_root):
        assert audit_assets.check_budgets(fake_root) == []


class TestFindingKey:
    def test_key_joins_asset_and_principle(self):
        f = audit_assets.Finding(5, "scripts/friction.py", "detail")
        assert f.key == "scripts/friction.py::P5"


class TestBaseline:
    """The metric. See the spec's Baseline section."""

    def test_p1_baseline_is_humanizer_only(self):
        found = audit_assets.check_trigger_shaped(REPO_ROOT)
        assert [f.asset for f in found] == ["skills/humanizer/SKILL.md"]

    def test_p3_baseline_is_clean(self):
        assert audit_assets.check_budgets(REPO_ROOT) == []
