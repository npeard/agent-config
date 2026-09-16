"""Contract tests for hooks/spec-retraction-check.py.

The hook is a JSON filter -- a payload on stdin, an optional payload on stdout
-- so it is exercised through that contract as a subprocess, like
tests/test_prose_writing.py.

TMPDIR is redirected per test because the once-per-session guard keeps a stamp
file under the temp directory. Without that, the guard's own tests leak into
each other and into a real session's state.

The false-positive cases carry as much weight here as the true positives. This
hook exists because a rule stated twice in prose was still violated, and the
way an advisory hook fails is by crying wolf until its reader learns to skip
it. A spec that merely *records* an earlier retraction as background must not
fire.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "spec-retraction-check.py"

SPEC = "/home/u/Documents/smi/docs/superpowers/report-revision-spec.md"
NOT_A_SPEC = "/home/u/Documents/smi/report/baseline.typ"


def run_hook(payload: dict, state: Path) -> str:
    # Created here, not left to the caller: tempfile.gettempdir() silently
    # ignores a TMPDIR that does not exist and falls back to the real system
    # temp directory, which would leak stamp files between tests.
    state.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "TMPDIR": str(state)},
    )
    return result.stdout.strip()


def write_payload(path: str, content: str, session: str = "s1") -> dict:
    return {
        "session_id": session,
        "cwd": "/home/u/Documents/smi",
        "tool_input": {"file_path": path, "content": content},
    }


def fired(payload: dict, state: Path) -> bool:
    out = run_hook(payload, state)
    if not out:
        return False
    parsed = json.loads(out)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    context = parsed["hookSpecificOutput"]["additionalContext"]
    # The advisory has to carry the rule and the reason, not just a flag. An
    # author who is told "this matched a pattern" cannot act; one who is told
    # what to write instead can.
    assert "replaces the claim it corrects" in context
    assert "state Y" in context
    return True


class TestFiresOnRetractionInstructions:
    """The cases this hook exists for, taken from the branch that motivated it."""

    @pytest.mark.parametrize(
        "text",
        [
            "### Specific claims to retract or rewrite",
            "Retract the 9-38% claim where it is asserted.",
            "The report must add a retraction of the earlier headline.",
            "Include a retraction subsection naming what changed.",
            "Structure it as: what the earlier draft claimed, then the fix.",
            "Section 4.2.1: what replaces it",
        ],
    )
    def test_instruction_shaped_language_fires(self, text: str, tmp_path: Path):
        assert fired(write_payload(SPEC, text), tmp_path)

    def test_the_real_spec_heading_fires(self, tmp_path: Path):
        """The exact heading that caused the defect, verbatim."""
        spec = (
            "## Phase 4: rewrite the report\n\n"
            "### Specific claims to retract or rewrite\n\n"
            "- Section 4.2's table -- these are global-fit numbers.\n"
        )
        assert fired(write_payload(SPEC, spec), tmp_path)


class TestDoesNotFireOnBackgroundOrNonSpecs:
    """False positives are how an advisory hook gets ignored."""

    def test_past_tense_background_does_not_fire(self, tmp_path: Path):
        """Recording an earlier finding is legitimate and common in a spec.

        This is the distinction the patterns are shaped around: a bare
        "retracted" describing history must not fire, or every spec with a
        background section becomes noise.
        """
        text = (
            "Correct controls are roughly 2x higher than the retracted "
            "figures: ~0.16-0.22 at W = 1024. The retracted numbers came "
            "from a window-mean denominator."
        )
        assert not fired(write_payload(SPEC, text), tmp_path)

    def test_a_report_is_not_a_spec(self, tmp_path: Path):
        """The report is the wrong place to intervene.

        By the time prose is being written the brief has already caused the
        defect, and hooks/prose-writing.py owns prose files anyway.
        """
        assert not fired(
            write_payload(NOT_A_SPEC, "Specific claims to retract"), tmp_path
        )

    def test_clean_spec_does_not_fire(self, tmp_path: Path):
        text = "## Item 4: show all three channels, individually and jointly fit."
        assert not fired(write_payload(SPEC, text), tmp_path)

    def test_non_markdown_in_the_spec_dir_does_not_fire(self, tmp_path: Path):
        path = "/home/u/Documents/smi/docs/superpowers/notes.txt"
        assert not fired(write_payload(path, "claims to retract"), tmp_path)


class TestSpecDetection:
    @pytest.mark.parametrize(
        "path",
        [
            "/home/u/p/docs/superpowers/x-spec.md",
            "/home/u/p/docs/specs/thing.md",
            "/home/u/p/specs/thing.md",
            "/home/u/p/scratch/feature-spec.md",
            "/home/u/p/scratch/feature_plan.md",
        ],
    )
    def test_recognized_as_spec(self, path: str, tmp_path: Path):
        assert fired(write_payload(path, "claims to retract"), tmp_path)

    @pytest.mark.parametrize(
        "path",
        [
            "/home/u/p/README.md",
            "/home/u/p/TASKS.md",
            "/home/u/p/docs/design.md",
        ],
    )
    def test_not_recognized_as_spec(self, path: str, tmp_path: Path):
        assert not fired(write_payload(path, "claims to retract"), tmp_path)


class TestEditsAndSessionGuard:
    def test_edit_new_string_is_scanned(self, tmp_path: Path):
        """Edit carries only the replacement, which is what should be scanned.

        Scanning the whole file instead would re-fire on every later edit to a
        spec whose offending line this edit does not touch.
        """
        payload = {
            "session_id": "s1",
            "cwd": "/home/u/Documents/smi",
            "tool_input": {
                "file_path": SPEC,
                "old_string": "a",
                "new_string": "Add a retraction of the 9-38% claim.",
            },
        }
        assert fired(payload, tmp_path)

    def test_fires_once_per_session_and_project(self, tmp_path: Path):
        text = "claims to retract"
        assert fired(write_payload(SPEC, text), tmp_path)
        assert not fired(write_payload(SPEC, text), tmp_path)

    def test_a_different_session_fires_again(self, tmp_path: Path):
        text = "claims to retract"
        assert fired(write_payload(SPEC, text, session="s1"), tmp_path)
        assert fired(write_payload(SPEC, text, session="s2"), tmp_path)

    def test_malformed_stdin_is_silent(self, tmp_path: Path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "TMPDIR": str(tmp_path)},
        )
        assert result.stdout.strip() == ""
