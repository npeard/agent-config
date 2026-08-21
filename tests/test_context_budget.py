"""Ceilings on context that is loaded whether or not it is needed.

Recurrence gating slows the growth of guidance; only a ceiling bounds it.
Always-loaded context grew from 1045 words to over 1200 across a single
branch, every addition individually justified -- which is how creep works.
Nobody adds a bad line.

So a failure here is the mechanism working, not a defect. The fix is to
evict, or to relocate the content to a tier that loads on demand. Raising a
ceiling is a real option but deserves the same deliberation as any other
change to what every session must read -- and changing a number in a test
should feel heavier than adding a sentence, which is the whole point.

The ceilings and the frontmatter parser now live in scripts/audit_assets.py
and are imported here. This file remains the gate -- it is what fails the
build -- while the script is the report the config-audit skill reads. They
are not duplicated in two places, because a test asserting that two copies
of a number agree is a test that a refactor happened.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from audit_assets import (
    CLAUDE_MD_MAX_WORDS,
    SKILL_BODY_MAX_WORDS,
    SKILL_DESCRIPTION_MAX_WORDS,
    description,
    skill_files,
    words,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

REMEDY = (
    "Evict content or move it to a lower tier (reference file, script, hook) "
    "rather than raising this ceiling; see the reflect skill."
)


def test_skills_exist():
    """Guards the two tests below from silently passing over an empty list."""
    assert skill_files()


def test_claude_md_within_budget():
    path = REPO_ROOT / "CLAUDE.md"
    n = words(path.read_text())
    assert n <= CLAUDE_MD_MAX_WORDS, (
        f"CLAUDE.md is {n} words, over the {CLAUDE_MD_MAX_WORDS} ceiling. "
        f"It is read in every session and inherited by every subagent. {REMEDY}"
    )


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_body_within_budget(path: Path):
    n = words(path.read_text())
    assert n <= SKILL_BODY_MAX_WORDS, (
        f"{path.parent.name}/SKILL.md is {n} words, over the "
        f"{SKILL_BODY_MAX_WORDS} ceiling. {REMEDY}"
    )


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_description_within_budget(path: Path):
    value = description(path.read_text())
    assert value, f"{path} has no description in its frontmatter"
    n = words(value)
    assert n <= SKILL_DESCRIPTION_MAX_WORDS, (
        f"{path.parent.name} description is {n} words, over the "
        f"{SKILL_DESCRIPTION_MAX_WORDS} ceiling. Descriptions are listed in "
        "every session, so this is always-loaded cost. Trim it to the trigger "
        "condition; the body carries the detail."
    )


class TestHumanizerPatternCount:
    """Three files state how many patterns the catalog has, and only the
    catalog knows. Same drift class as TestStandardsPointerIntegrity below:
    adding or removing a pattern silently falsifies every statement of the
    count, and splitting the catalog out of SKILL.md is what made the number
    a cross-file claim in the first place.
    """

    def catalog(self) -> Path:
        return REPO_ROOT / "skills" / "humanizer" / "patterns.md"

    def actual(self) -> int:
        headings = re.findall(
            r"^### (\d+)\. ", self.catalog().read_text(), re.MULTILINE
        )
        return len(headings)

    def test_patterns_are_numbered_consecutively_from_one(self):
        numbers = re.findall(r"^### (\d+)\. ", self.catalog().read_text(), re.MULTILINE)
        assert numbers == [str(i) for i in range(1, len(numbers) + 1)]

    @pytest.mark.parametrize(
        "relative",
        [
            "skills/humanizer/SKILL.md",
            "skills/humanizer/patterns.md",
            "README.md",
        ],
    )
    def test_every_file_that_states_the_count_states_the_right_one(self, relative: str):
        n = self.actual()
        text = (REPO_ROOT / relative).read_text()
        stated = re.findall(r"(\d+)[ -]patterns?\b", text)
        assert stated, f"{relative} no longer states the pattern count"
        wrong = [s for s in stated if s != str(n)]
        assert not wrong, (
            f"{relative} says {wrong} patterns but patterns.md defines {n}"
        )


class TestDescriptionExtraction:
    """The gate is only as good as its parser; these are the two ways it
    silently passed a description it should have measured."""

    def test_folded_scalar_is_measured_not_read_as_one_word(self):
        text = (
            "---\n"
            "name: x\n"
            "description: >\n"
            "  one two three four five\n"
            "  six seven eight\n"
            "---\n\n# Body\n"
        )
        assert words(description(text)) == 8

    def test_plain_scalar_wrapping_onto_the_next_line_is_included(self):
        text = "---\nname: x\ndescription: one two\n  three four\n---\n"
        assert words(description(text)) == 4

    def test_body_line_starting_with_description_is_not_measured(self):
        text = "---\nname: x\ndescription: real one\n---\n\ndescription: a b c d e\n"
        assert words(description(text)) == 2

    def test_missing_frontmatter_yields_none_so_the_assertion_fires(self):
        assert description("# Just a heading\n") is None


class TestStandardsPointerIntegrity:
    """CLAUDE.md's Coding standards preamble promises that each bullet is
    defined with an example in CODING_STANDARDS.md. It listed ten bullets
    against nine rules, so a reader following the pointer for the tenth
    found nothing -- a broken promise no other check would notice.
    """

    def bullets(self) -> list[str]:
        text = (REPO_ROOT / "CLAUDE.md").read_text()
        section = text[text.index("## Coding standards") :]
        section = section[: section.index("\n## ", 3)]
        return re.findall(r"^- \*\*(.+?)\*\*", section, re.MULTILINE | re.DOTALL)

    def rules(self) -> list[str]:
        path = (
            REPO_ROOT / "skills" / "standards-and-spec-review" / "CODING_STANDARDS.md"
        )
        return re.findall(r"^## (\d+)\. ", path.read_text(), re.MULTILINE)

    def test_every_bullet_has_a_defined_rule(self):
        assert len(self.bullets()) == len(self.rules()), (
            f"CLAUDE.md lists {len(self.bullets())} standards bullets but "
            f"CODING_STANDARDS.md defines {len(self.rules())} rules. The "
            "preamble promises each bullet is defined there."
        )

    def test_rules_are_numbered_consecutively_from_one(self):
        assert self.rules() == [str(i) for i in range(1, len(self.rules()) + 1)]

    def test_the_review_skill_states_the_right_count(self):
        """SKILL.md names the number of rules, so it drifts silently too."""
        path = REPO_ROOT / "skills" / "standards-and-spec-review" / "SKILL.md"
        spelled = {
            8: "eight",
            9: "nine",
            10: "ten",
            11: "eleven",
            12: "twelve",
            13: "thirteen",
            14: "fourteen",
        }
        n = len(self.rules())
        word = spelled.get(n)
        # A KeyError here would hide what actually needs updating, which is
        # the opposite of what a drift gate is for.
        assert word, f"no spelling known for {n} rules; extend this table"
        assert word in path.read_text(), (
            f"SKILL.md should say '{word} house rules' for {n} rules"
        )
