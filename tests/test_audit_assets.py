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

    def test_claude_md_is_covered_too(self, fake_root):
        (fake_root / "CLAUDE.md").write_text("Run scripts/ghost.py\n")
        assert any(
            "ghost.py" in f.detail
            for f in audit_assets.check_script_references(fake_root)
        )


class TestBaselineTaskTwo:
    def test_p2_baseline_is_clean(self):
        assert audit_assets.check_evidence(REPO_ROOT) == []

    def test_p4_help_baseline_is_the_two_known_scripts(self):
        found = audit_assets.check_script_help(REPO_ROOT)
        assert sorted(f.asset for f in found) == [
            "scripts/check_ascii.py",
            "scripts/suppressions.py",
        ]

    def test_p4_reference_baseline_is_clean(self):
        assert audit_assets.check_script_references(REPO_ROOT) == []


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


class TestBaselineTaskThree:
    def test_p5_baseline_is_the_six_enumerated_candidates(self):
        """The spec's Baseline names these. Six of eleven is wide on purpose;
        four are expected to end up ledgered with a stated trust boundary."""
        found = audit_assets.check_read_and_emit(REPO_ROOT)
        assert sorted(f.asset for f in found) == [
            "hooks/notify.py",
            "hooks/prose-writing.py",
            "hooks/task-list.py",
            "scripts/friction.py",
            "scripts/preflight.py",
            "scripts/toolgaps.py",
        ]


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
        live, suppressed = audit_assets.partition([f], ledger, fake_root)
        assert live == [] and suppressed == [f]

    def test_stale_sha_lets_the_finding_return(self, fake_root):
        target = fake_root / "scripts" / "mute.py"
        target.write_text("x = 1\n")
        f = audit_assets.Finding(4, "scripts/mute.py", "detail")
        live, suppressed = audit_assets.partition([f], {f.key: "stale"}, fake_root)
        assert live == [f] and suppressed == []

    def test_a_ledger_entry_is_scoped_to_one_principle(self, fake_root):
        target = fake_root / "scripts" / "mute.py"
        target.write_text("x = 1\n")
        ledger = {"scripts/mute.py::P4": audit_assets.sha(target)}
        other = audit_assets.Finding(5, "scripts/mute.py", "detail")
        live, _ = audit_assets.partition([other], ledger, fake_root)
        assert live == [other]

    def test_missing_ledger_file_is_not_an_error(self, tmp_path):
        assert audit_assets.load_ledger(tmp_path / "none.toml") == {}

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
        assert set(payload) == {"findings", "suppressed"}

    def test_no_ledger_reports_accepted_exceptions_as_findings(self, capsys):
        audit_assets.main(["--json", "--no-ledger"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["suppressed"] == []
