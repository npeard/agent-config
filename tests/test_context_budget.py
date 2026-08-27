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
build -- while the script is the report the config-audit skill reads. The
measurements are not reimplemented here, because a test asserting that two
copies of an implementation agree is a test that a refactor happened.

The ceiling *values* are a different thing, and are pinned below as literals
on purpose: see test_ceilings_have_not_been_loosened.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from audit_assets import (
    CLAUDE_MD_MAX_WORDS,
    REFERENCE_MAX_WORDS,
    SKILL_BODY_MAX_WORDS,
    SKILL_DESCRIPTION_MAX_WORDS,
    SKILL_EFFECTIVE_MAX_WORDS,
    description,
    effective_words,
    reference_files,
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


ALL_REFERENCES = [ref for path in skill_files() for ref in reference_files(path.parent)]


def test_reference_files_exist():
    """Guards the parametrized test below from passing over an empty list."""
    assert ALL_REFERENCES


@pytest.mark.parametrize(
    "path", ALL_REFERENCES, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_reference_file_within_budget(path: Path):
    """An on-demand file is the cheap tier, not a free one.

    Nothing measured these, so moving prose out of SKILL.md converted a
    measured cost into an invisible one -- and that was the sanctioned way to
    get under the body ceiling.
    """
    n = words(path.read_text(encoding="utf-8"))
    assert n <= REFERENCE_MAX_WORDS, (
        f"{path.parent.name}/{path.name} is {n} words, over the "
        f"{REFERENCE_MAX_WORDS} ceiling. {REMEDY}"
    )


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_invocation_within_budget(path: Path):
    """SKILL.md plus every reference an imperative step tells the reader to
    read -- what one invocation of the skill actually costs.

    humanizer measured 4878 words this way against a 1261-word body, because
    step 1 is literally "Read `patterns.md`".
    """
    n = effective_words(path, path.read_text())
    assert n <= SKILL_EFFECTIVE_MAX_WORDS, (
        f"{path.parent.name} costs {n} words per invocation, over the "
        f"{SKILL_EFFECTIVE_MAX_WORDS} ceiling. Make a reference conditional "
        f"or split it. {REMEDY}"
    )


def test_ceilings_have_not_been_loosened():
    """A one-way ratchet. The literals are here on purpose.

    When the ceilings moved out of this file into scripts/audit_assets.py,
    this file's own promise -- that changing a number should feel heavier
    than adding a sentence -- went with them: raising CLAUDE_MD_MAX_WORDS
    from 1250 to 1400 turns every gate above green with no record of the old
    value, and scripts/thresholds.py could not see it either, because
    pairing required the substring "assert" (it now reads named limits too,
    so this is belt and braces, and the braces are the cheap half).

    This is *not* a test that asserts a refactor happened. That rule is
    about asserting two implementations agree; here the literal is the
    policy, and the duplication is the mechanism: tightening a ceiling
    passes this untouched, loosening one cannot happen without editing a
    test. Do not "simplify" it by comparing against the imported names.
    """
    assert CLAUDE_MD_MAX_WORDS <= 1250
    assert SKILL_BODY_MAX_WORDS <= 2000
    assert SKILL_DESCRIPTION_MAX_WORDS <= 60
    assert REFERENCE_MAX_WORDS <= 2000
    assert SKILL_EFFECTIVE_MAX_WORDS <= 4000


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
            r"^### (\d+)\. ", self.catalog().read_text(encoding="utf-8"), re.MULTILINE
        )
        return len(headings)

    def test_patterns_are_numbered_consecutively_from_one(self):
        numbers = re.findall(
            r"^### (\d+)\. ", self.catalog().read_text(encoding="utf-8"), re.MULTILINE
        )
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
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        stated = re.findall(r"(\d+)[ -]patterns?\b", text)
        assert stated, f"{relative} no longer states the pattern count"
        wrong = [s for s in stated if s != str(n)]
        assert not wrong, (
            f"{relative} says {wrong} patterns but patterns.md defines {n}"
        )

    def headings(self, path: Path) -> dict[str, str]:
        return dict(
            re.findall(
                r"^### (\d+)\. (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE
            )
        )

    def test_every_worked_example_matches_its_catalog_entry(self):
        """examples.md promises "numbered as in patterns.md", and the numbers
        are the only way to get from one file to the other. Renumbering or
        retitling a pattern on one side silently sends the reader to the
        wrong rewrite -- the drift this split introduced, and the reason it
        is gated rather than trusted.
        """
        catalog = self.headings(self.catalog())
        examples = self.headings(REPO_ROOT / "skills" / "humanizer" / "examples.md")
        assert examples, "examples.md no longer has numbered entries"
        mismatched = {
            n: (title, catalog.get(n))
            for n, title in examples.items()
            if catalog.get(n) != title
        }
        assert not mismatched, (
            f"examples.md entries disagree with patterns.md: {mismatched}"
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
