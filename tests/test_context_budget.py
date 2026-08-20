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
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Measured at the time of writing plus deliberately tight headroom.
CLAUDE_MD_MAX_WORDS = 1250

# A skill body is paid only by sessions that invoke the skill, so this is
# looser than CLAUDE.md -- but a skill nobody can finish reading is not
# cheaper than prose, it is just less likely to be followed.
SKILL_BODY_MAX_WORDS = 2000

# Descriptions are the one part of a skill that IS always loaded: they are
# listed in every session so the model can decide what to invoke. A verbose
# description is therefore a permanent tax, and the tightest budget here.
SKILL_DESCRIPTION_MAX_WORDS = 60

REMEDY = (
    "Evict content or move it to a lower tier (reference file, script, hook) "
    "rather than raising this ceiling; see the reflect skill."
)


def words(text: str) -> int:
    return len(text.split())


def frontmatter(text: str) -> str | None:
    """The YAML block between the leading `---` fences, if any."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else None


def description(text: str) -> str | None:
    """The description value, including folded continuation lines.

    A regex capturing to end-of-line reads `description: >` as the single
    word ">" and lets an arbitrarily long description through the budget.
    Searching the whole file rather than the frontmatter would also measure
    a body line that merely starts with "description:".
    """
    block = frontmatter(text)
    if block is None:
        return None
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        # A folded or literal scalar puts the text on the indented lines
        # that follow; a plain scalar may also wrap onto them.
        parts = [] if value in (">", "|", ">-", "|-") else [value]
        for cont in lines[i + 1 :]:
            if not cont[:1].isspace() or not cont.strip():
                break
            parts.append(cont.strip())
        return " ".join(parts)
    return None


def skill_files() -> list[Path]:
    return sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))


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
