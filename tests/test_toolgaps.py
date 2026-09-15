"""Tests for scripts/toolgaps.py.

Includes a structural test that no capability here duplicates a preflight
check. The two scripts were nearly duplicates when first specified, and
nothing but a test stops a future addition from quietly re-merging them.
"""

from __future__ import annotations

import re
from pathlib import Path

import preflight
import pytest
import toolgaps


class TestMatches:
    def test_bare_word_needs_a_word_boundary(self):
        """ "flow" inside "workflow" reported a type checker that did not
        exist -- found on the first real run, before this test."""
        assert not toolgaps.matches("flow", "workflow-orchestration")
        assert toolgaps.matches("flow", "uses flow for types")

    def test_punctuated_needles_match_plainly(self):
        """`\\b` behaves badly next to a leading dot, and a filename is
        specific enough not to need the boundary."""
        assert toolgaps.matches(".editorconfig", "root/.editorconfig here")
        assert toolgaps.matches(".github/workflows", "see .github/workflows/ci.yml")

    def test_matching_is_case_insensitive_on_the_needle(self):
        assert toolgaps.matches("MyPy".lower(), "mypy configured")


class TestGaps:
    def test_empty_project_has_every_capability_missing(self, tmp_path: Path):
        found = [name for name, ev in toolgaps.gaps(tmp_path) if ev]
        assert found == []

    def test_detects_tools_declared_only_inside_a_config_file(self, tmp_path: Path):
        """A tool configured in pyproject.toml leaves no filename behind, so
        evidence has to read contents, not just list the directory."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.mypy]\nstrict = true\n[tool.ruff]\n"
        )
        present = dict(toolgaps.gaps(tmp_path))
        assert present["type checker"]
        assert present["linter"]

    def test_detects_tools_declared_only_as_precommit_hooks(self, tmp_path: Path):
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "repos:\n  - repo: x\n    hooks:\n      - id: codespell\n"
        )
        assert dict(toolgaps.gaps(tmp_path))["spell check"]

    def test_detects_ci_by_directory(self, tmp_path: Path):
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        assert dict(toolgaps.gaps(tmp_path))["ci"]

    def test_reports_every_capability_exactly_once(self, tmp_path: Path):
        names = [n for n, _ in toolgaps.gaps(tmp_path)]
        assert len(names) == len(set(names)) == len(toolgaps.CAPABILITIES)

    def test_unreadable_root_does_not_raise(self, tmp_path: Path):
        assert toolgaps.evidence(tmp_path / "nonexistent") == ""


class TestAssets:
    def test_absent_claude_config_is_empty_not_an_error(self, tmp_path: Path):
        assert toolgaps.assets(tmp_path / "nope") == {}

    def test_inventories_scripts_hooks_and_skills(self, tmp_path: Path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "thing.py").write_text("")
        (tmp_path / "hooks").mkdir()
        (tmp_path / "hooks" / "guard.py").write_text("")
        (tmp_path / "skills" / "some-skill").mkdir(parents=True)
        (tmp_path / "skills" / "some-skill" / "SKILL.md").write_text("")
        found = toolgaps.assets(tmp_path)
        assert found["scripts"] == ["thing.py"]
        assert found["hooks"] == ["guard.py"]
        assert found["skills"] == ["some-skill"]


class TestNoOverlapWithPreflight:
    """The consolidation decision, enforced rather than merely documented."""

    def test_capabilities_do_not_restate_preflight_checks(self):
        preflight_labels = set(
            re.findall(
                r'report\.add\([A-Z]+,\s*"([^"]+)"',
                Path(preflight.__file__).read_text(),
            )
        )
        capability_names = {name for name, _ in toolgaps.CAPABILITIES}
        assert not (capability_names & preflight_labels), (
            "toolgaps must not re-check what preflight already reports: "
            "preflight owns state, toolgaps owns capability."
        )

    @pytest.mark.parametrize("owned_by_preflight", ["pre-commit", "test"])
    def test_state_checks_stay_out_of_capabilities(self, owned_by_preflight: str):
        """Both of these were in the first draft of the capability list and
        were removed by the redundancy check."""
        names = " ".join(name for name, _ in toolgaps.CAPABILITIES)
        assert owned_by_preflight not in names

    def test_both_scripts_state_the_boundary(self):
        """A boundary nobody can find is a boundary that will be crossed."""
        for module in (toolgaps, preflight):
            doc = module.__doc__ or ""
            assert "capability" in doc and "state" in doc, module.__name__


class TestRepoRoot:
    """A cwd-based scan from a subdirectory finds none of the root's config
    files and reports every capability absent. That is a wrong answer, and
    reflect feeds it straight into proposing tools the project already has.
    """

    def test_resolves_the_repo_root_from_a_subdirectory(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        nested = git_repo / "deep" / "deeper"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        assert toolgaps.repo_root().resolve() == git_repo.resolve()

    def test_gaps_are_identical_from_root_and_subdirectory(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (git_repo / "ruff.toml").write_text("target-version = 'py312'\n")
        (git_repo / "sub").mkdir()
        monkeypatch.chdir(git_repo)
        from_root = toolgaps.gaps(toolgaps.repo_root())
        monkeypatch.chdir(git_repo / "sub")
        assert toolgaps.gaps(toolgaps.repo_root()) == from_root

    def test_falls_back_to_cwd_outside_a_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(tmp_path)
        assert toolgaps.repo_root().resolve() == tmp_path.resolve()


class TestNoAssetsFlag:
    def test_honoured_in_json_output(self, capsys: pytest.CaptureFixture):
        """A caller passing --no-assets is asking us not to touch the
        agent-config directory; the json path ignored it."""
        import json as _json

        toolgaps.main(["--json", "--no-assets"])
        assert _json.loads(capsys.readouterr().out)["assets"] == {}

    def test_assets_present_without_the_flag(self, capsys: pytest.CaptureFixture):
        import json as _json

        toolgaps.main(["--json"])
        payload = _json.loads(capsys.readouterr().out)
        assert isinstance(payload["assets"], dict)

    def test_detects_ty_as_a_type_checker(self, tmp_path: Path):
        """`ty` is the type checker these projects use, declared as a hook id
        or a bare dependency pin. It was missing from the needle list, so every
        ty project reported a phantom type-checker gap.
        """
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pixi.feature.dev.dependencies]\nty = "*"\n'
        )
        assert dict(toolgaps.gaps(tmp_path))["type checker"] == "ty"

    def test_detects_ty_declared_only_as_a_precommit_hook(self, tmp_path: Path):
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "repos:\n  - repo: local\n    hooks:\n      - id: ty\n"
            "        entry: pixi run -e dev ty check\n"
        )
        assert dict(toolgaps.gaps(tmp_path))["type checker"] == "ty"

    @pytest.mark.parametrize("decoy", ["typescript", "mypy", "security", "typing"])
    def test_ty_does_not_match_words_containing_it(self, tmp_path: Path, decoy: str):
        """The bare needle is only safe because `matches` anchors on word
        boundaries. If that anchoring regresses, "ty" silently reports a type
        checker for any project mentioning "typing" -- a false pass, which is
        worse than the false gap it replaced.
        """
        (tmp_path / "notes.md").write_text(f"we care about {decoy} here\n")
        assert "ty" not in dict(toolgaps.gaps(tmp_path))["type checker"].split(", ")

    def test_a_config_name_inside_a_regex_still_counts_as_evidence(
        self, tmp_path: Path
    ):
        """Documents a known limit rather than asserting a fix.

        A `files:` regex listing mypy.ini among many config names is a ruff
        hook's filter, not a mypy install, but substring search over declaration
        files cannot tell the two apart -- separating them needs parsing per
        file format, which costs more than the wrong answer does.

        It is recorded because it is how this repo passed its own type-checker
        check while the `ty` needle was missing: a false pass concealed a false
        gap, so nobody looked. The mitigation is the `ty` needle being present,
        not this heuristic getting smarter.
        """
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "repos:\n  - repo: local\n    hooks:\n      - id: ruff\n"
            r"        files: '(/mypy\.ini|/setup\.cfg)$'" + "\n"
        )
        assert dict(toolgaps.gaps(tmp_path))["type checker"] == "mypy"
