"""Tests for scripts/audit_assets.py.

Each check gets a fixture that violates it and one that does not, because a
check that fires on everything and a check that fires on nothing both pass a
single-fixture test.

The baseline tests are the success metric made executable: the spec measured
nine findings on the tree as it stood, and those tests are what make "fixed
or ledgered" checkable rather than asserted.
"""

from __future__ import annotations

import json
import subprocess
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
    """A minimal repo shaped like agent-config, with nothing wrong in it."""
    (tmp_path / "skills").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "hooks").mkdir()
    (tmp_path / "AGENTS.md").write_text("word " * 10)
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
    def test_oversized_agents_md_is_reported(self, fake_root):
        (fake_root / "AGENTS.md").write_text(
            "word " * (audit_assets.AGENTS_MD_MAX_WORDS + 1)
        )
        found = audit_assets.check_budgets(fake_root)
        assert [f.asset for f in found] == ["AGENTS.md"]
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


class TestBudgetBands:
    """Every budget warns before it fails, and the two bands are distinct.

    A single-band test cannot tell a warning from a failure, which is the
    whole distinction this adds: the warn band reports a cost and the fail
    band refuses the asset. Each budget is checked at both boundaries because
    four budgets sharing one comparison helper is four chances for a pair to
    be wired to the wrong constant.
    """

    BANDS = (
        ("AGENTS_MD_WARN_WORDS", "AGENTS_MD_MAX_WORDS"),
        ("SKILL_BODY_WARN_WORDS", "SKILL_BODY_MAX_WORDS"),
        ("REFERENCE_WARN_WORDS", "REFERENCE_MAX_WORDS"),
        ("SKILL_EFFECTIVE_WARN_WORDS", "SKILL_EFFECTIVE_MAX_WORDS"),
    )

    @pytest.mark.parametrize(("warn_name", "fail_name"), BANDS)
    def test_warn_band_is_below_the_fail_band(self, warn_name, fail_name):
        warn = getattr(audit_assets, warn_name)
        fail = getattr(audit_assets, fail_name)
        assert warn < fail, f"{warn_name} must be under {fail_name}"

    def test_at_the_warn_threshold_is_silent(self):
        assert audit_assets.budget("a", 2000, 2000, 4800, 3, "2000 words") == []

    def test_one_over_the_warn_threshold_warns_without_failing(self):
        found = audit_assets.budget("a", 2001, 2000, 4800, 3, "2001 words")
        assert len(found) == 1
        assert found[0].warning is True
        assert "2000 warn threshold" in found[0].detail

    def test_at_the_fail_ceiling_still_only_warns(self):
        found = audit_assets.budget("a", 4800, 2000, 4800, 3, "4800 words")
        assert found[0].warning is True

    def test_one_over_the_fail_ceiling_fails(self):
        found = audit_assets.budget("a", 4801, 2000, 4800, 3, "4801 words")
        assert len(found) == 1
        assert found[0].warning is False
        assert "over the 4800 ceiling" in found[0].detail

    def test_a_warning_names_the_three_questions_it_asks(self):
        """The warn text routes the judgement to reflect rather than deciding
        "useless" in a checker, so losing the prompt makes the band useless."""
        found = audit_assets.budget("a", 2001, 2000, 4800, 3, "2001 words")
        for probe in ("duplicated intent", "reflect", "decays", "new skill"):
            assert probe in found[0].detail

    def test_a_finding_is_a_failure_unless_it_says_otherwise(self):
        """A check that became advisory by accident is worse than no check."""
        assert audit_assets.Finding(3, "a", "detail").warning is False

    def test_partition_splits_warnings_from_failures(self):
        warn = audit_assets.Finding(3, "w", "d", warning=True)
        fail = audit_assets.Finding(3, "f", "d")
        assert audit_assets.partition([warn, fail]) == ([fail], [warn])

    def test_strict_promotes_warnings_to_failures(self):
        """The nightly loop runs unsupervised, so it keeps the hard band."""
        warn = audit_assets.Finding(3, "w", "d", warning=True)
        fail = audit_assets.Finding(3, "f", "d")
        assert audit_assets.partition([warn, fail], strict=True) == (
            [warn, fail],
            [],
        )

    def test_a_warning_does_not_fail_the_run(self, fake_root):
        (fake_root / "AGENTS.md").write_text(
            "word " * (audit_assets.AGENTS_MD_WARN_WORDS + 1)
        )
        found = audit_assets.check_budgets(fake_root)
        assert [f.warning for f in found] == [True]
        failures, warnings = audit_assets.partition(found)
        assert failures == []
        assert len(warnings) == 1


class TestReferenceBudgets:
    """Nothing measured a reference file, so the sanctioned way to bring a
    skill under its body ceiling was to move prose into a file no check could
    see. Verified before this existed: a 17-word SKILL.md beside a
    50,006-word catalog.md produced no finding at all.
    """

    def reference(self, root: Path, skill: str, name: str, n: int) -> None:
        (root / "skills" / skill / name).write_text("word " * n)

    def test_an_oversized_reference_file_is_reported(self, fake_root):
        write_skill(fake_root, "big", "Use when big")
        self.reference(
            fake_root, "big", "catalog.md", audit_assets.REFERENCE_MAX_WORDS + 1
        )
        found = audit_assets.check_budgets(fake_root)
        assert "skills/big/catalog.md" in [f.asset for f in found]
        assert all(f.principle == 3 for f in found)

    def test_a_reference_within_its_ceiling_is_silent(self, fake_root):
        """Silent means under the *warn* band. At REFERENCE_MAX_WORDS the file
        is over warn and under fail, so it warns rather than saying nothing --
        which is the two-band behaviour, not a regression."""
        write_skill(fake_root, "big", "Use when big")
        self.reference(
            fake_root, "big", "catalog.md", audit_assets.REFERENCE_WARN_WORDS
        )
        assert audit_assets.check_budgets(fake_root) == []

    def test_a_nested_reference_is_measured_too(self, fake_root):
        """references/<file>.md is the layout superpowers:writing-skills
        prescribes, so a top-level-only scan would miss the common case."""
        write_skill(fake_root, "deep", "Use when deep")
        (fake_root / "skills" / "deep" / "references").mkdir()
        self.reference(
            fake_root,
            "deep",
            "references/r.md",
            audit_assets.REFERENCE_MAX_WORDS + 1,
        )
        assert "skills/deep/references/r.md" in [
            f.asset for f in audit_assets.check_budgets(fake_root)
        ]

    def test_required_references_count_toward_the_invocation_cost(self, fake_root):
        """Each file is under its own ceiling; together they are what one
        invocation of the skill actually costs."""
        write_skill(
            fake_root,
            "heavy",
            "Use when heavy",
            "Read `a.md`.\n\nRead `b.md`.\n\n" + "word " * 1900,
        )
        self.reference(fake_root, "heavy", "a.md", 1900)
        self.reference(fake_root, "heavy", "b.md", 1900)
        found = audit_assets.check_budgets(fake_root)
        assert "skills/heavy" in [f.asset for f in found]
        assert "per invocation" in next(
            f.detail for f in found if f.asset == "skills/heavy"
        )

    def test_a_reference_nothing_tells_the_reader_to_read_does_not_count(
        self, fake_root
    ):
        """The cost of a genuinely conditional file is not paid every time,
        and charging for it would punish exactly the arrangement principle 3
        asks for."""
        write_skill(fake_root, "heavy", "Use when heavy", "Deeper detail in a.md.\n")
        self.reference(fake_root, "heavy", "a.md", 1900)
        self.reference(fake_root, "heavy", "b.md", 1900)
        assert audit_assets.check_budgets(fake_root) == []

    def test_read_on_demand_is_not_an_imperative_step(self, fake_root):
        """config-audit's own phrasing: the file is *named* before the word
        "read", and the sentence says the read is conditional."""
        write_skill(
            fake_root,
            "ondemand",
            "Use when ondemand",
            "The rules are defined in `a.md`, read on demand.\n",
        )
        self.reference(fake_root, "ondemand", "a.md", 1900)
        assert audit_assets.check_budgets(fake_root) == []

    def test_a_read_instruction_inside_a_fence_is_an_example_not_a_step(
        self, fake_root
    ):
        write_skill(
            fake_root,
            "quoted",
            "Use when quoted",
            "A flagged example:\n\n```\nRead `a.md` before rewriting.\n```\n",
        )
        self.reference(fake_root, "quoted", "a.md", 1900)
        assert audit_assets.check_budgets(fake_root) == []

    def test_a_named_file_that_is_not_in_the_skill_directory_is_not_charged(
        self, fake_root
    ):
        """A skill may tell the reader to read the *project's* file of the
        same name; only this repo's own copy is a cost this repo controls."""
        write_skill(
            fake_root,
            "outside",
            "Use when outside",
            "Read `CLAUDE.md` first.\n" + "word " * 1900,
        )
        assert audit_assets.check_budgets(fake_root) == []


class TestFindingKey:
    def test_key_joins_asset_and_principle(self):
        f = audit_assets.Finding(5, "scripts/friction.py", "detail")
        assert f.key == "scripts/friction.py::P5"


class TestEvidence:
    def test_skill_with_no_table_or_example_anywhere_is_reported(self, fake_root):
        write_skill(fake_root, "bare", "Use when bare", "# Body\n\nJust prose.\n")
        found = audit_assets.check_evidence(fake_root)
        assert [f.asset for f in found] == ["skills/bare"]
        assert found[0].principle == 2

    def test_table_in_skill_md_satisfies_it(self, fake_root):
        write_skill(fake_root, "tabled", "Use when tabled")
        assert audit_assets.check_evidence(fake_root) == []

    def test_fenced_code_block_satisfies_it(self, fake_root):
        write_skill(fake_root, "fenced", "Use when fenced", "# B\n\n```\nx = 1\n```\n")
        assert audit_assets.check_evidence(fake_root) == []

    def test_evidence_in_a_reference_file_satisfies_it(self, fake_root):
        """The humanizer case. Its catalog lives in patterns.md exactly as
        principle 3 prescribes, so a SKILL.md-only check would punish
        compliance with one principle in the name of another."""
        write_skill(fake_root, "split", "Use when split", "# B\n\nSee patterns.md.\n")
        (fake_root / "skills" / "split" / "patterns.md").write_text(
            "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
        )
        assert audit_assets.check_evidence(fake_root) == []

    def test_labelled_worked_example_satisfies_it(self, fake_root):
        """The real humanizer shape. Its catalog is before/after pairs with no
        table and no code fence, and a check that knew only those two reported
        the most evidence-dense skill in the repo as evidence-free."""
        write_skill(
            fake_root,
            "worked",
            "Use when worked",
            "# B\n\n**Words to watch:** x\n\n**Before:** a\n\n**After:** b\n",
        )
        assert audit_assets.check_evidence(fake_root) == []

    def test_asset_is_the_directory_so_the_ledger_key_is_stable(self, fake_root):
        write_skill(fake_root, "bare", "Use when bare", "# Body\n\nJust prose.\n")
        assert audit_assets.check_evidence(fake_root)[0].key == "skills/bare::P2"


class TestScriptHelp:
    def test_script_without_argparse_is_reported(self, fake_root):
        (fake_root / "scripts" / "mute.py").write_text("import sys\nprint(sys.argv)\n")
        found = audit_assets.check_script_help(fake_root)
        assert [f.asset for f in found] == ["scripts/mute.py"]
        assert found[0].principle == 4

    def test_script_with_argparse_is_silent(self, fake_root):
        (fake_root / "scripts" / "ok.py").write_text(
            "import argparse\np = argparse.ArgumentParser()\n"
        )
        assert audit_assets.check_script_help(fake_root) == []

    def test_a_usage_docstring_alone_does_not_satisfy_it(self, fake_root):
        """The exact shape of the two baseline violations: documented for a
        human reading the file, undiscoverable for an agent that should not
        have to."""
        (fake_root / "scripts" / "doc.py").write_text('"""Usage:\n    doc.py X\n"""\n')
        assert audit_assets.check_script_help(fake_root)


class TestScriptReferences:
    def test_dangling_script_path_is_reported(self, fake_root):
        write_skill(fake_root, "ref", "Use when ref", "# B\n\nRun scripts/ghost.py.\n")
        found = audit_assets.check_script_references(fake_root)
        assert any("ghost.py" in f.detail for f in found)

    def test_existing_script_path_is_silent(self, fake_root):
        (fake_root / "scripts" / "real.py").write_text("import argparse\n")
        write_skill(fake_root, "ref", "Use when ref", "# B\n\nRun scripts/real.py.\n")
        assert audit_assets.check_script_references(fake_root) == []

    def test_dangling_pixi_task_is_reported(self, fake_root):
        write_skill(fake_root, "ref", "Use when ref", "# B\n\nRun `pixi run nope`.\n")
        found = audit_assets.check_script_references(fake_root)
        assert any("pixi run nope" in f.detail for f in found)

    def test_existing_pixi_task_is_silent(self, fake_root):
        write_skill(fake_root, "ref", "Use when ref", "# B\n\nRun `pixi run fmt`.\n")
        assert audit_assets.check_script_references(fake_root) == []

    def test_a_feature_scoped_pixi_task_counts_as_existing(self, fake_root):
        """Six real tasks looked dangling because they live under
        [feature.dev.tasks] rather than [tasks]."""
        (fake_root / "pixi.toml").write_text(
            '[tasks]\nfmt = "true"\n\n[feature.dev.tasks]\ncheck = "true"\n'
        )
        write_skill(fake_root, "ref", "Use when ref", "# B\n\nRun `pixi run check`.\n")
        assert audit_assets.check_script_references(fake_root) == []

    def test_instruction_to_read_a_script_is_reported(self, fake_root):
        (fake_root / "scripts" / "real.py").write_text("import argparse\n")
        write_skill(
            fake_root,
            "ref",
            "Use when ref",
            "# B\n\nRead scripts/real.py to see the flags.\n",
        )
        found = audit_assets.check_script_references(fake_root)
        assert any("instructs reading" in f.detail for f in found)

    def test_a_read_instruction_inside_a_fence_is_an_example_not_a_directive(
        self, fake_root
    ):
        """AGENT_ASSET_PRINCIPLES.md documents this anti-pattern with a Flag:
        example, so a check that cannot tell a counter-example from a
        directive reports the file teaching the rule as breaking it."""
        (fake_root / "scripts" / "real.py").write_text("import argparse\n")
        write_skill(
            fake_root,
            "ref",
            "Use when ref",
            "# B\n\n```markdown\n# Flag\nRead scripts/real.py for the flags.\n```\n",
        )
        assert audit_assets.check_script_references(fake_root) == []

    def test_a_read_instruction_in_prose_is_still_reported(self, fake_root):
        """The fence exemption must not swallow the real case."""
        (fake_root / "scripts" / "real.py").write_text("import argparse\n")
        write_skill(
            fake_root,
            "ref",
            "Use when ref",
            "# B\n\nRead scripts/real.py for the flags.\n\n```\nx = 1\n```\n",
        )
        assert audit_assets.check_script_references(fake_root)

    def test_a_name_inside_a_fence_still_has_to_resolve(self, fake_root):
        """Only the instruction check is fence-exempt. A pointer in a fenced
        command block is still a pointer a reader will follow."""
        write_skill(
            fake_root, "ref", "Use when ref", "# B\n\n```\npixi run nope\n```\n"
        )
        assert audit_assets.check_script_references(fake_root)

    def test_agents_md_is_covered_too(self, fake_root):
        (fake_root / "AGENTS.md").write_text("Run scripts/ghost.py\n")
        assert any(
            "ghost.py" in f.detail
            for f in audit_assets.check_script_references(fake_root)
        )


class TestReadAndEmit:
    def test_untrusted_read_plus_emit_is_reported(self, fake_root):
        (fake_root / "scripts" / "leaky.py").write_text(
            "import argparse\n"
            "from pathlib import Path\n"
            "t = Path('~/.claude/projects/a.jsonl').read_text()\n"
            "print(t)\n"
        )
        found = audit_assets.check_read_and_emit(fake_root)
        assert [f.asset for f in found] == ["scripts/leaky.py"]
        assert found[0].principle == 5
        assert "transcript" in found[0].detail

    def test_read_without_emit_is_silent(self, fake_root):
        (fake_root / "scripts" / "quiet.py").write_text(
            "from pathlib import Path\nt = Path('a.jsonl').read_text()\n"
        )
        assert audit_assets.check_read_and_emit(fake_root) == []

    def test_emit_without_untrusted_read_is_silent(self, fake_root):
        (fake_root / "scripts" / "talky.py").write_text("x = 1\nprint(x)\n")
        assert audit_assets.check_read_and_emit(fake_root) == []

    def test_print_of_a_bare_literal_is_not_an_emit(self, fake_root):
        (fake_root / "scripts" / "lit.py").write_text(
            "from pathlib import Path\nPath('a.jsonl').read_text()\nprint('done')\n"
        )
        assert audit_assets.check_read_and_emit(fake_root) == []

    def test_hooks_are_covered_and_agent_context_is_a_sink(self, fake_root):
        (fake_root / "hooks" / "h.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            "t = Path('pixi.toml').read_text()\n"
            'print(json.dumps({"additionalContext": t}))\n'
        )
        found = audit_assets.check_read_and_emit(fake_root)
        assert [f.asset for f in found] == ["hooks/h.py"]
        assert "agent-context" in found[0].detail

    def test_the_audit_script_does_not_report_itself(self):
        """It holds every pattern as data, so a naive scan flags it and the
        finding can never be resolved."""
        found = audit_assets.check_read_and_emit(REPO_ROOT)
        assert audit_assets.SELF not in [Path(f.asset).name for f in found]


class TestSha:
    def test_file_sha_is_content_addressed(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("one")
        first = audit_assets.sha(p)
        p.write_text("two")
        assert first != audit_assets.sha(p)

    def test_directory_sha_covers_its_markdown(self, tmp_path):
        """P2 findings name a directory, so suppression needs a hash for one."""
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("a")
        first = audit_assets.sha(d)
        (d / "patterns.md").write_text("b")
        assert first != audit_assets.sha(d)

    def test_directory_sha_covers_non_markdown_evidence(self, tmp_path):
        """Hashing only *.md left the ledger's expiry promise false for a
        skill whose evidence is a code sample or a fixture."""
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("a")
        (d / "example.py").write_text("x = 1")
        first = audit_assets.sha(d)
        (d / "example.py").write_text("x = 2")
        assert first != audit_assets.sha(d)

    def test_directory_sha_ignores_pycache(self, tmp_path):
        d = tmp_path / "skill"
        (d / "__pycache__").mkdir(parents=True)
        (d / "SKILL.md").write_text("a")
        first = audit_assets.sha(d)
        (d / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        assert first == audit_assets.sha(d)


class TestPairSha:
    def make(self, root, name, text):
        d = root / "skills" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(text)

    def test_either_half_changing_expires_the_pair(self, fake_root):
        self.make(fake_root, "aaa", "one")
        self.make(fake_root, "bbb", "two")
        asset = "skills/aaa+skills/bbb"
        first = audit_assets.asset_sha(fake_root, asset)
        self.make(fake_root, "bbb", "changed")
        assert first != audit_assets.asset_sha(fake_root, asset)

    def test_a_single_asset_hashes_to_its_own_digest(self, fake_root):
        target = fake_root / "scripts" / "x.py"
        target.write_text("x = 1\n")
        assert audit_assets.asset_sha(fake_root, "scripts/x.py") == audit_assets.sha(
            target
        )

    def test_a_missing_half_is_none_so_nothing_is_suppressed(self, fake_root):
        self.make(fake_root, "aaa", "one")
        assert audit_assets.asset_sha(fake_root, "skills/aaa+skills/gone") is None

    def test_renaming_a_reference_file_expires_the_exception(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / "patterns.md").write_text("a")
        first = audit_assets.sha(d)
        (d / "patterns.md").rename(d / "catalog.md")
        assert first != audit_assets.sha(d)

    def test_missing_path_is_none_rather_than_an_error(self, tmp_path):
        assert audit_assets.sha(tmp_path / "gone") is None


class TestLedger:
    def entry(self, asset, principle, asset_sha):
        return (
            "[[decision]]\n"
            f'asset = "{asset}"\n'
            f"principle = {principle}\n"
            'date = "2026-08-21"\n'
            'cause = "working-as-designed"\n'
            'outcome = "tier-0"\n'
            f'asset_sha = "{asset_sha}"\n'
            'note = "because"\n'
        )

    def test_matching_sha_suppresses_the_finding(self, fake_root):
        target = fake_root / "scripts" / "mute.py"
        target.write_text("x = 1\n")
        f = audit_assets.Finding(4, "scripts/mute.py", "detail")
        ledger = {f.key: audit_assets.sha(target)}
        live, _, suppressed = audit_assets.triage([f], ledger, fake_root)
        assert live == [] and suppressed == [f]

    def test_stale_sha_lets_the_finding_return(self, fake_root):
        target = fake_root / "scripts" / "mute.py"
        target.write_text("x = 1\n")
        f = audit_assets.Finding(4, "scripts/mute.py", "detail")
        live, _, suppressed = audit_assets.triage([f], {f.key: "stale"}, fake_root)
        assert live == [f] and suppressed == []

    def test_a_ledger_entry_is_scoped_to_one_principle(self, fake_root):
        target = fake_root / "scripts" / "mute.py"
        target.write_text("x = 1\n")
        ledger = {"scripts/mute.py::P4": audit_assets.sha(target)}
        other = audit_assets.Finding(5, "scripts/mute.py", "detail")
        live, _, _ = audit_assets.triage([other], ledger, fake_root)
        assert live == [other]

    def test_missing_ledger_file_is_not_an_error(self, tmp_path):
        assert audit_assets.load_ledger(tmp_path / "none.toml") == {}

    def test_entry_missing_a_note_fails_loudly(self, tmp_path):
        """A suppression with no recorded reason is worse than no entry: it
        reads as decided."""
        p = tmp_path / "l.toml"
        p.write_text(
            self.entry("scripts/x.py", 5, "abc").replace('note = "because"', "")
        )
        with pytest.raises(SystemExit) as e:
            audit_assets.load_ledger(p)
        assert "note" in str(e.value)

    def test_entry_with_a_blank_note_fails_loudly(self, tmp_path):
        p = tmp_path / "l.toml"
        p.write_text(self.entry("scripts/x.py", 5, "abc").replace('"because"', '"   "'))
        with pytest.raises(SystemExit) as e:
            audit_assets.load_ledger(p)
        assert "note" in str(e.value)

    def test_entry_missing_a_required_field_fails_loudly(self, tmp_path):
        """Without asset_sha the exception would never expire, which is how
        friction-ledger's count_at_decision rule fails when omitted."""
        p = tmp_path / "l.toml"
        p.write_text('[[decision]]\nasset = "a"\nprinciple = 1\n')
        with pytest.raises(SystemExit) as e:
            audit_assets.load_ledger(p)
        assert "asset_sha" in str(e.value)

    def test_loaded_entries_are_keyed_asset_and_principle(self, tmp_path):
        p = tmp_path / "l.toml"
        p.write_text(self.entry("scripts/x.py", 5, "abc"))
        assert audit_assets.load_ledger(p) == {"scripts/x.py::P5": "abc"}


class TestCli:
    def test_sha_flag_prints_a_hash_so_a_ledger_entry_needs_no_source_read(
        self, capsys
    ):
        rc = audit_assets.main(["--sha", "scripts/friction.py"])
        out = capsys.readouterr().out.strip()
        assert rc == 0 and len(out) == 64

    def test_sha_flag_on_a_missing_asset_is_an_error(self):
        assert audit_assets.main(["--sha", "scripts/ghost.py"]) == 2

    def test_json_reports_live_and_suppressed_separately(self, capsys):
        audit_assets.main(["--json"])
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {
            "findings",
            "warnings",
            "awaiting_regrant",
            "suppressed",
        }

    def test_no_ledger_reports_accepted_exceptions_as_findings(self, capsys):
        audit_assets.main(["--json", "--no-ledger"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["suppressed"] == []


class TestRepoIsClean:
    """The success metric, kept live.

    The spec measured nine findings; each is now fixed or ledgered, and this
    is what stops the count drifting back up. A failure names the asset and
    the principle: fix it, or add a ledger entry with a cause. Do not delete
    this test.
    """

    def test_no_live_findings(self):
        failures, _ = audit_assets.partition(audit_assets.audit(REPO_ROOT))
        live, _, _ = audit_assets.triage(
            failures, audit_assets.load_ledger(), REPO_ROOT
        )
        assert live == [], "\n".join(
            f"P{f.principle} {f.asset}: {f.detail}" for f in live
        )

    def test_every_ledger_entry_still_matches_its_asset(self):
        """Catches an exception granted to content that has since moved, and
        an asset that left the flagged set entirely -- which nothing else
        would.

        Scoped to assets this branch has *not* touched. An entry stale because
        the branch is mid-edit is the expected state, not a defect: the note is
        re-granted once, against the asset's final form. The docstring here
        used to say a stale entry "is not an error" while the assertion made it
        one, and that contradiction is what charged a re-grant per commit.
        `changed_assets` is empty on the default branch, so nothing is excused
        once the work lands.

        Goes through asset_sha, not sha: a pairwise key is not a path, so sha
        returns None for one and this reported the first ledgered P1 overlap
        exception -- the case PAIR_SEP exists for -- as permanently stale.
        """
        changed = audit_assets.changed_assets(REPO_ROOT)
        stale = [
            key
            for key, recorded in audit_assets.load_ledger().items()
            if audit_assets.asset_sha(REPO_ROOT, key.split("::")[0]) != recorded
            and not audit_assets.touched(key.split("::")[0], changed)
        ]
        assert not stale, f"ledger entries no longer match their asset: {stale}"

    def test_every_ledger_entry_names_a_finding_that_still_exists(self):
        """An exception for a finding that no longer fires is dead weight, and
        reads as though the asset were still a problem."""
        keys = {f.key for f in audit_assets.audit(REPO_ROOT)}
        orphans = sorted(set(audit_assets.load_ledger()) - keys)
        assert not orphans, f"ledger entries with no matching finding: {orphans}"


class TestOverlap:
    def test_near_identical_descriptions_are_reported_as_a_pair(self, fake_root):
        write_skill(
            fake_root, "one", "Use when reviewing prose for stock phrasing and filler"
        )
        write_skill(
            fake_root, "two", "Use when reviewing prose for filler and stock phrasing"
        )
        found = audit_assets.check_overlap(fake_root)
        assert len(found) == 1
        assert found[0].principle == 1
        assert found[0].asset == "skills/one+skills/two"

    def test_distinct_descriptions_are_silent(self, fake_root):
        write_skill(fake_root, "one", "Use when drawing quantum circuit diagrams")
        write_skill(fake_root, "two", "Use when a deploy fails during rollout")
        assert audit_assets.check_overlap(fake_root) == []

    def test_shared_boilerplate_alone_is_not_overlap(self, fake_root):
        """Every description here opens with the same trigger words. If those
        counted, the check would report every pair and be useless."""
        write_skill(fake_root, "one", "Use when the alpha subsystem misbehaves")
        write_skill(fake_root, "two", "Use when the beta pipeline stalls")
        assert audit_assets.check_overlap(fake_root) == []

    def test_the_pair_is_ordered_so_the_ledger_key_is_stable(self, fake_root):
        write_skill(fake_root, "bbb", "Use when reviewing prose for stock filler words")
        write_skill(fake_root, "aaa", "Use when reviewing prose for filler stock words")
        found = audit_assets.check_overlap(fake_root)
        assert found[0].key == "skills/aaa+skills/bbb::P1"

    def test_two_overlaps_sharing_one_skill_get_distinct_keys(self, fake_root):
        """Keyed on one asset, A-overlaps-B and A-overlaps-C collided, so a
        ledger entry reviewed for one silently suppressed the other."""
        for name in ("aaa", "bbb", "ccc"):
            write_skill(fake_root, name, "Use when reviewing prose for stock filler")
        keys = {f.key for f in audit_assets.check_overlap(fake_root)}
        assert len(keys) == 3

    def test_the_score_is_reported_so_a_reader_can_judge_the_threshold(self, fake_root):
        write_skill(fake_root, "one", "Use when reviewing prose for stock phrasing")
        write_skill(fake_root, "two", "Use when reviewing prose for stock phrasing")
        assert "1.00" in audit_assets.check_overlap(fake_root)[0].detail

    def test_the_real_repo_has_headroom_under_the_threshold(self):
        """The threshold was set from this measurement; if it ever fires here,
        read the pair before touching the number."""
        score, first, second = audit_assets.max_overlap(REPO_ROOT)
        # A literal bound, not OVERLAP_THRESHOLD: comparing against the
        # threshold is implied by check_overlap returning nothing, and both
        # assertions keep passing if the threshold is raised to hide a pair.
        assert score < 0.25, f"{first} and {second} now overlap at {score:.2f}"


class TestClearOwed:
    """A warning nobody can clear is a warning everyone learns to ignore."""

    def test_clear_owed_removes_the_marker(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(audit_assets, "REPO_ROOT", tmp_path)
        marker = tmp_path / ".audit-owed"
        marker.write_text("scripts/x.py\n")
        assert audit_assets.main(["--clear-owed"]) == 0
        assert not marker.exists()
        assert "cleared" in capsys.readouterr().out

    def test_clear_owed_drops_an_unscoped_legacy_line(
        self, monkeypatch, tmp_path, capsys
    ):
        """Its "branch" field is the asset path, so testing that against the
        current branch never matched and the line could never be cleared."""
        monkeypatch.setattr(audit_assets, "REPO_ROOT", tmp_path)
        marker = tmp_path / ".audit-owed"
        marker.write_text("scripts/legacy.py\n")
        assert audit_assets.main(["--clear-owed"]) == 0
        assert not marker.exists()

    def test_clear_owed_keeps_another_branch_s_entries(self, monkeypatch, tmp_path):
        monkeypatch.setattr(audit_assets, "REPO_ROOT", tmp_path)
        marker = tmp_path / ".audit-owed"
        marker.write_text("other\tscripts/x.py\n")
        assert audit_assets.main(["--clear-owed"]) == 0
        assert marker.read_text().strip() == "other\tscripts/x.py"

    def test_clear_owed_with_no_marker_says_so(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(audit_assets, "REPO_ROOT", tmp_path)
        assert audit_assets.main(["--clear-owed"]) == 0
        assert "no audit owed" in capsys.readouterr().out


class TestP5Severity:
    """The rule splits on how foreign the content is, not on how loud the sink
    is. Narrowing to high-severity sinks alone was the obvious move and would
    have exempted friction.py -- the case that motivated the principle."""

    def write(self, root, where, name, body):
        (root / where).mkdir(parents=True, exist_ok=True)
        (root / where / name).write_text(body)

    def assets(self, root):
        return {f.asset for f in audit_assets.check_read_and_emit(root)}

    def test_foreign_content_to_plain_stdout_is_reported(self, fake_root):
        """A script's stdout is read by the agent that ran it, so for content
        this repo did not author stdout is not a weak sink."""
        self.write(
            fake_root,
            "scripts",
            "miner.py",
            "from pathlib import Path\nt = Path('a.jsonl').read_text()\nprint(t)\n",
        )
        assert "scripts/miner.py" in self.assets(fake_root)

    def test_weak_content_to_plain_stdout_is_not_reported(self, fake_root):
        """preflight and toolgaps read manifests to decide booleans and print
        check names. A standing ledger entry for that is noise."""
        self.write(
            fake_root,
            "scripts",
            "tools.py",
            "from pathlib import Path\nok = Path('pixi.toml').exists()\nprint(ok)\n",
        )
        assert self.assets(fake_root) == set()

    def test_weak_content_to_agent_context_is_reported(self, fake_root):
        self.write(
            fake_root,
            "hooks",
            "h.py",
            "import json\nfrom pathlib import Path\n"
            "t = Path('pixi.toml').read_text()\n"
            'print(json.dumps({"additionalContext": t}))\n',
        )
        assert "hooks/h.py" in self.assets(fake_root)

    def test_weak_content_to_a_shell_argument_is_reported(self, fake_root):
        self.write(
            fake_root,
            "hooks",
            "n.py",
            "import subprocess\n"
            "msg = subprocess.run(['git', 'log'], capture_output=True).stdout\n"
            "subprocess.run(['osascript', '-e', msg])\n",
        )
        assert "hooks/n.py" in self.assets(fake_root)

    def test_a_sink_with_no_source_is_not_reported(self, fake_root):
        """promotion-check.py emits into agent context but reads nothing from
        outside the repo; a rule keyed on the sink alone reported it."""
        self.write(
            fake_root,
            "hooks",
            "p.py",
            'import json\nmsg = "fixed text"\n'
            'print(json.dumps({"additionalContext": msg}))\n',
        )
        assert self.assets(fake_root) == set()


class TestEvidenceDepthAndKind:
    """Found by a subagent pressure test, not by a check: check_evidence read
    only markdown while sha() hashed every file, so the two disagreed about
    what a skill directory contains."""

    def test_a_code_sample_is_evidence_on_its_own(self, fake_root):
        write_skill(fake_root, "sample", "Use when sample", "# B\n\nSee example.py.\n")
        (fake_root / "skills" / "sample" / "example.py").write_text("x = 1\n")
        assert audit_assets.check_evidence(fake_root) == []

    def test_a_fixture_in_a_subdirectory_is_evidence(self, fake_root):
        write_skill(fake_root, "fx", "Use when fx", "# B\n\nprose only\n")
        (fake_root / "skills" / "fx" / "fixtures").mkdir()
        (fake_root / "skills" / "fx" / "fixtures" / "in.json").write_text("{}")
        assert audit_assets.check_evidence(fake_root) == []

    def test_prose_only_markdown_at_any_depth_is_still_reported(self, fake_root):
        write_skill(fake_root, "bare", "Use when bare", "# B\n\nprose only\n")
        (fake_root / "skills" / "bare" / "references").mkdir()
        (fake_root / "skills" / "bare" / "references" / "more.md").write_text("prose\n")
        assert [f.asset for f in audit_assets.check_evidence(fake_root)] == [
            "skills/bare"
        ]

    def test_pycache_alone_is_not_evidence(self, fake_root):
        write_skill(fake_root, "cached", "Use when cached", "# B\n\nprose only\n")
        (fake_root / "skills" / "cached" / "__pycache__").mkdir()
        (fake_root / "skills" / "cached" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        assert [f.asset for f in audit_assets.check_evidence(fake_root)] == [
            "skills/cached"
        ]


class TestProseFilesDepth:
    def test_a_dangling_reference_in_a_subdirectory_is_found(self, fake_root):
        """Latent only because every reference file in this repo currently sits
        at its skill's top level."""
        write_skill(fake_root, "deep", "Use when deep")
        (fake_root / "skills" / "deep" / "references").mkdir()
        (fake_root / "skills" / "deep" / "references" / "r.md").write_text(
            "Run scripts/ghost.py\n"
        )
        found = audit_assets.check_script_references(fake_root)
        assert any("ghost.py" in f.detail for f in found)


class TestAssetDocumented:
    """The reverse direction of check_script_references. Nothing asked whether
    an asset was documented, so three shipped undocumented and no gate saw it.
    """

    def readme(self, root, body):
        (root / "README.md").write_text(body)

    def test_an_undocumented_hook_is_reported(self, fake_root):
        (fake_root / "hooks" / "ghost.py").write_text("x = 1\n")
        self.readme(fake_root, "# r\n")
        found = audit_assets.check_asset_documented(fake_root)
        assert "hooks/ghost.py" in [f.asset for f in found]
        assert found[0].principle == 4

    def test_a_bare_filename_counts_as_documented(self, fake_root):
        """README groups the generic scripts into one bullet listing filenames
        rather than paths."""
        (fake_root / "scripts" / "tool.py").write_text("x = 1\n")
        self.readme(fake_root, "- `scripts/` -- generic tools (`tool.py`)\n")
        # Not `== []`: the fixture ships an undocumented `alpha` skill, so the
        # assertion has to be about this asset rather than about the whole tree.
        assert "scripts/tool.py" not in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_a_full_path_counts_as_documented(self, fake_root):
        (fake_root / "hooks" / "h.py").write_text("x = 1\n")
        self.readme(fake_root, "- `hooks/h.py` -- does a thing\n")
        assert "hooks/h.py" not in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_an_undocumented_skill_directory_is_reported(self, fake_root):
        write_skill(fake_root, "orphan", "Use when orphan")
        self.readme(fake_root, "# r\n")
        assert "skills/orphan" in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_a_missing_readme_is_not_an_error(self, fake_root):
        (fake_root / "hooks" / "h.py").write_text("x = 1\n")
        assert audit_assets.check_asset_documented(fake_root) == []

    def test_a_mention_only_inside_a_code_fence_does_not_count(self, fake_root):
        """The finding says "add a Layout entry", and a name in a command
        block is a usage example rather than a description of the asset.
        Verified: a README whose only mention was a fenced `ls skills/bloated`
        satisfied the check."""
        write_skill(fake_root, "bloated", "Use when bloated")
        self.readme(fake_root, "## Layout\n\n```\nls skills/bloated\n```\n")
        assert "skills/bloated" in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_a_mention_outside_the_layout_section_does_not_count(self, fake_root):
        write_skill(fake_root, "bloated", "Use when bloated")
        self.readme(
            fake_root,
            "## Install\n\nRun skills/bloated somehow.\n\n## Layout\n\n- nothing\n",
        )
        assert "skills/bloated" in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_the_layout_section_ends_at_the_next_heading(self, fake_root):
        write_skill(fake_root, "bloated", "Use when bloated")
        self.readme(
            fake_root,
            "## Layout\n\n- nothing\n\n## Notes\n\n- `skills/bloated` exists\n",
        )
        assert "skills/bloated" in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_a_name_that_is_only_a_suffix_of_a_documented_one_does_not_count(
        self, fake_root
    ):
        """A future `scripts/ascii.py` passed on README's existing mention of
        `check_ascii.py`, so the check would stay silent about a genuinely
        undocumented script."""
        (fake_root / "scripts" / "ascii.py").write_text("x = 1\n")
        self.readme(fake_root, "## Layout\n\n- `check_ascii.py` -- checks ascii\n")
        assert "scripts/ascii.py" in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_a_readme_with_no_layout_section_falls_back_to_the_whole_file(
        self, fake_root
    ):
        """A missing section is a README problem; reporting every asset at
        once would be a check nobody reads."""
        (fake_root / "hooks" / "h.py").write_text("x = 1\n")
        self.readme(fake_root, "# r\n\n- `hooks/h.py` -- does a thing\n")
        assert "hooks/h.py" not in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]

    def test_a_layout_entry_still_counts(self, fake_root):
        (fake_root / "hooks" / "h.py").write_text("x = 1\n")
        self.readme(fake_root, "## Layout\n\n- `hooks/h.py` -- does a thing\n")
        assert "hooks/h.py" not in [
            f.asset for f in audit_assets.check_asset_documented(fake_root)
        ]


class TestUntrackedJunk:
    """macOS supplies a .DS_Store for free on a Finder visit. Two checks
    depended on directory contents and both mishandled it."""

    def test_a_dotfile_does_not_count_as_evidence(self, fake_root):
        """ "Any non-markdown file is evidence" meant one .DS_Store silently
        exempted a skill from the evidence check."""
        write_skill(fake_root, "bare", "Use when bare", "# B\n\nprose only\n")
        (fake_root / "skills" / "bare" / ".DS_Store").write_bytes(b"\x00")
        assert [f.asset for f in audit_assets.check_evidence(fake_root)] == [
            "skills/bare"
        ]

    def test_a_named_evidence_suffix_still_counts(self, fake_root):
        write_skill(fake_root, "sample", "Use when sample", "# B\n\nprose only\n")
        (fake_root / "skills" / "sample" / "demo.py").write_text("x = 1\n")
        assert audit_assets.check_evidence(fake_root) == []

    def test_a_dotfile_does_not_change_the_digest(self, tmp_path):
        """It expired a ledgered exception with no content change, and since
        `audit` is a dependency of `pixi run all`, turned the build red."""
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").write_text("a")
        first = audit_assets.sha(d)
        (d / ".DS_Store").write_bytes(b"\x00")
        assert audit_assets.sha(d) == first

    def test_a_dotfile_in_a_subdirectory_is_also_ignored(self, tmp_path):
        d = tmp_path / "skill"
        (d / "references").mkdir(parents=True)
        (d / "SKILL.md").write_text("a")
        first = audit_assets.sha(d)
        (d / "references" / ".DS_Store").write_bytes(b"\x00")
        assert audit_assets.sha(d) == first


class TestBinaryFilesInSkillDirs:
    """`audit` is a dependency of `pixi run all`, so a crash here breaks the
    whole build. An earlier version read every file it listed, so one stray
    image did exactly that."""

    def test_a_binary_file_does_not_crash_the_evidence_check(self, fake_root):
        write_skill(fake_root, "img", "Use when img")
        (fake_root / "skills" / "img" / "diagram.png").write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00"
        )
        assert audit_assets.check_evidence(fake_root) == []

    def test_a_binary_file_is_not_itself_evidence(self, fake_root):
        """It is not in EVIDENCE_SUFFIXES, so it must not exempt a skill that
        has no evidence at all."""
        write_skill(fake_root, "bare", "Use when bare", "# B\n\nprose only\n")
        (fake_root / "skills" / "bare" / "diagram.png").write_bytes(b"\x89PNG\r\n")
        assert [f.asset for f in audit_assets.check_evidence(fake_root)] == [
            "skills/bare"
        ]

    def test_the_whole_audit_survives_a_binary_file(self, fake_root):
        write_skill(fake_root, "img", "Use when img")
        (fake_root / "skills" / "img" / "x.png").write_bytes(b"\x00\x01\x02")
        audit_assets.audit(fake_root)


class TestDischargeIsRecorded:
    """Clearing used to delete the marker, so nothing could tell "never
    audited" from "audited, then changed again". The obligation is now stamped
    with the hash it was discharged against, which is what lets a premature
    clear correct itself instead of silently standing."""

    def write_asset(self, root: Path, body: str = "x = 1\n") -> str:
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "x.py").write_text(body)
        return "scripts/x.py"

    def test_clearing_stamps_the_hash_rather_than_forgetting(
        self, monkeypatch, git_repo, capsys
    ):
        asset = self.write_asset(git_repo)
        monkeypatch.setattr(audit_assets, "REPO_ROOT", git_repo)
        (git_repo / ".audit-owed").write_text(f"main\t{asset}\n")
        assert audit_assets.main(["--clear-owed"]) == 0
        assert "cleared" in capsys.readouterr().out
        recorded = (git_repo / ".audit-owed").read_text().splitlines()
        digest = audit_assets.asset_sha(git_repo, asset)
        # The obligation survives; the discharge is what answers it. Consuming
        # the obligation instead left nothing for a later edit to re-open.
        assert recorded == [f"main\t{asset}", f"main\t{asset}\t{digest}"]

    def test_editing_an_audited_asset_re_opens_it_with_no_hook_write(
        self, monkeypatch, git_repo, capsys
    ):
        """The self-correcting property. An earlier version consumed the
        obligation on clear, so `owed_assets` had nothing to report against and
        a branch audited too early stayed silent until the hook next fired."""
        asset = self.write_asset(git_repo)
        monkeypatch.setattr(audit_assets, "REPO_ROOT", git_repo)
        (git_repo / ".audit-owed").write_text(f"main\t{asset}\n")
        assert audit_assets.main(["--clear-owed"]) == 0
        capsys.readouterr()
        assert audit_assets.owed_assets(git_repo, "main", any_branch=False) == []
        self.write_asset(git_repo, "x = 2\n")
        assert audit_assets.owed_assets(git_repo, "main", any_branch=False) == [asset]

    def test_the_default_branch_sees_every_branch_s_obligations(self, git_repo):
        """Merged work is the default branch's contents, so an obligation
        recorded against feat/x is now its to discharge."""
        asset = self.write_asset(git_repo)
        (git_repo / ".audit-owed").write_text(f"feat/x\t{asset}\n")
        assert audit_assets.owed_assets(git_repo, "main", any_branch=False) == []
        assert audit_assets.owed_assets(git_repo, "main", any_branch=True) == [asset]

    def test_the_count_reports_obligations_not_lines_lost(
        self, monkeypatch, git_repo, capsys
    ):
        """Clearing converts rather than deletes, so counting the file's lost
        lines reported "cleared 0 entry(s)" for a branch whose one obligation
        had just been recorded."""
        asset = self.write_asset(git_repo)
        monkeypatch.setattr(audit_assets, "REPO_ROOT", git_repo)
        (git_repo / ".audit-owed").write_text(f"main\t{asset}\n")
        assert audit_assets.main(["--clear-owed"]) == 0
        assert "cleared 1 obligation(s)" in capsys.readouterr().out

    def test_an_asset_unchanged_since_its_audit_is_not_owed(self, git_repo):
        asset = self.write_asset(git_repo)
        digest = audit_assets.asset_sha(git_repo, asset)
        (git_repo / ".audit-owed").write_text(
            f"main\t{asset}\nmain\t{asset}\t{digest}\n"
        )
        assert audit_assets.owed_assets(git_repo, "main", any_branch=False) == []

    def test_an_asset_changed_since_its_audit_is_owed_again(self, git_repo):
        asset = self.write_asset(git_repo)
        stale = audit_assets.asset_sha(git_repo, asset)
        self.write_asset(git_repo, "x = 2\n")
        (git_repo / ".audit-owed").write_text(
            f"main\t{asset}\nmain\t{asset}\t{stale}\n"
        )
        assert audit_assets.owed_assets(git_repo, "main", any_branch=False) == [asset]

    def test_a_discharge_alone_never_makes_an_asset_owed(self, git_repo):
        """The stamp is a record that the audit happened, not a request for
        one. Read as an obligation it would make every cleared branch dirty."""
        asset = self.write_asset(git_repo)
        (git_repo / ".audit-owed").write_text(f"main\t{asset}\tdeadbeef\n")
        assert audit_assets.owed_assets(git_repo, "main", any_branch=False) == []

    def test_a_vanished_asset_lapses_rather_than_being_stamped(
        self, monkeypatch, git_repo
    ):
        """An obligation for a file the branch deleted has nothing left to
        audit, and there is no hash to stamp it against."""
        monkeypatch.setattr(audit_assets, "REPO_ROOT", git_repo)
        (git_repo / ".audit-owed").write_text("main\tscripts/gone.py\n")
        assert audit_assets.main(["--clear-owed"]) == 0
        assert not (git_repo / ".audit-owed").exists()

    def test_another_branch_s_discharge_survives_this_branch_s_clear(
        self, monkeypatch, git_repo
    ):
        asset = self.write_asset(git_repo)
        monkeypatch.setattr(audit_assets, "REPO_ROOT", git_repo)
        subprocess.run(
            ["git", "branch", "other"], cwd=git_repo, check=True, capture_output=True
        )
        (git_repo / ".audit-owed").write_text(
            f"other\tscripts/y.py\tcafe\nmain\t{asset}\n"
        )
        assert audit_assets.main(["--clear-owed"]) == 0
        assert "other\tscripts/y.py\tcafe" in (git_repo / ".audit-owed").read_text()


class TestRegrantGrace:
    """`pixi run all` used to go red the moment a ledgered asset was edited and
    stay red until the note was rewritten, which is what charged one re-grant
    per commit instead of one per branch. The grace is narrow on purpose."""

    def finding(self, root: Path, principle: int = 4) -> audit_assets.Finding:
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "mute.py").write_text("x = 1\n")
        return audit_assets.Finding(principle, "scripts/mute.py", "detail")

    def test_a_granted_exception_on_a_touched_asset_awaits_rather_than_fails(
        self, monkeypatch, fake_root
    ):
        f = self.finding(fake_root)
        monkeypatch.setattr(audit_assets, "changed_assets", lambda _: {f.asset})
        live, awaiting, _ = audit_assets.triage([f], {f.key: "stale"}, fake_root)
        assert live == [] and awaiting == [f]

    def test_a_new_violation_on_a_touched_asset_still_fails(
        self, monkeypatch, fake_root
    ):
        """The grace is for re-justifying an accepted exception, not for
        waving through a violation nobody has ever judged."""
        f = self.finding(fake_root)
        monkeypatch.setattr(audit_assets, "changed_assets", lambda _: {f.asset})
        live, awaiting, _ = audit_assets.triage([f], {}, fake_root)
        assert live == [f] and awaiting == []

    def test_a_stale_exception_on_an_untouched_asset_still_fails(
        self, monkeypatch, fake_root
    ):
        """Stale for some reason other than this branch's work -- the case the
        gate exists for -- is unaffected."""
        f = self.finding(fake_root)
        monkeypatch.setattr(audit_assets, "changed_assets", lambda _: set())
        live, awaiting, _ = audit_assets.triage([f], {f.key: "stale"}, fake_root)
        assert live == [f] and awaiting == []

    def test_either_half_of_a_pair_counts_as_touched(self, monkeypatch, fake_root):
        f = audit_assets.Finding(1, "skills/aaa+skills/bbb", "detail")
        monkeypatch.setattr(audit_assets, "changed_assets", lambda _: {"skills/bbb"})
        live, awaiting, _ = audit_assets.triage([f], {f.key: "stale"}, fake_root)
        assert live == [] and awaiting == [f]

    def test_a_file_under_a_ledgered_directory_counts_as_touched(
        self, monkeypatch, fake_root
    ):
        f = audit_assets.Finding(2, "skills/alpha", "detail")
        monkeypatch.setattr(
            audit_assets, "changed_assets", lambda _: {"skills/alpha/SKILL.md"}
        )
        live, awaiting, _ = audit_assets.triage([f], {f.key: "stale"}, fake_root)
        assert live == [] and awaiting == [f]

    def test_awaiting_does_not_fail_the_command(self, monkeypatch, capsys):
        """Exit 0 is the whole point: the branch stays buildable while the
        obligation stays visible."""
        f = audit_assets.Finding(4, "scripts/mute.py", "detail")
        monkeypatch.setattr(audit_assets, "audit", lambda *a: [f])
        monkeypatch.setattr(audit_assets, "load_ledger", lambda *a: {f.key: "stale"})
        monkeypatch.setattr(audit_assets, "changed_assets", lambda _: {f.asset})
        assert audit_assets.main([]) == 0
        assert "awaiting re-grant" in capsys.readouterr().out

    def test_the_same_finding_fails_once_the_branch_has_landed(
        self, monkeypatch, capsys
    ):
        """On the default branch nothing is changed relative to itself, so the
        grace evaporates with no branch name written down anywhere."""
        f = audit_assets.Finding(4, "scripts/mute.py", "detail")
        monkeypatch.setattr(audit_assets, "audit", lambda *a: [f])
        monkeypatch.setattr(audit_assets, "load_ledger", lambda *a: {f.key: "stale"})
        monkeypatch.setattr(audit_assets, "changed_assets", lambda _: set())
        assert audit_assets.main([]) == 1

    def test_git_failure_grants_no_grace(self, monkeypatch, tmp_path):
        """Failing closed: if git cannot say what changed, the gate holds."""
        assert audit_assets.changed_assets(tmp_path) == set()
