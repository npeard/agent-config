"""Tests for scripts/nightly.py.

The gate is the whole artifact, so the tests are about when it declines. A
loop that wakes a model on a quiet night is the failure mode this script
exists to prevent, and it is invisible in production -- nobody notices a
session that should not have happened.
"""

from __future__ import annotations

import nightly
import pytest


@pytest.fixture
def staging(tmp_path, monkeypatch):
    """Redirect the brief and log into a temp dir."""
    monkeypatch.setattr(nightly, "BRIEF", tmp_path / ".nightly-brief")
    monkeypatch.setattr(nightly, "LOG", tmp_path / ".nightly-log")
    return tmp_path


QUIET = {"actionable": [], "actionable_count": 0, "window_since": "2026-08-16"}
BUSY = {
    "actionable": [{"name": "windows-path-quoting", "count": 4}],
    "actionable_count": 1,
    "window_since": "2026-08-16",
}


class TestReasons:
    def test_no_friction_and_clean_audit_is_no_reason(self):
        assert nightly.reasons(QUIET, {"findings": []}, {"gaps": []}) == []

    def test_friction_over_the_bar_is_a_reason(self):
        found = nightly.reasons(BUSY, None, None)
        assert len(found) == 1
        assert "windows-path-quoting" in found[0]

    def test_a_live_audit_finding_is_a_reason(self):
        found = nightly.reasons(QUIET, {"findings": [{"asset": "AGENTS.md"}]}, None)
        assert any("audit" in line and "AGENTS.md" in line for line in found)

    def test_a_tool_gap_is_a_reason(self):
        found = nightly.reasons(QUIET, None, {"gaps": ["editorconfig"]})
        assert any("editorconfig" in line for line in found)

    def test_a_failed_friction_run_is_never_a_reason(self):
        """A crashed instrument must not read as 'nothing found'."""
        assert nightly.reasons(None, {"findings": [{"asset": "x"}]}, None) == []


class TestGate:
    def test_a_quiet_night_writes_no_brief(self, staging, monkeypatch):
        monkeypatch.setattr(
            nightly,
            "instrument",
            lambda name, args: QUIET if name == "friction" else {},
        )
        assert nightly.main([]) == 0
        assert not nightly.BRIEF.exists()
        assert "quiet" in nightly.LOG.read_text()

    def test_a_quiet_night_still_logs(self, staging, monkeypatch):
        """Silence and 'the job did not run' must be distinguishable later."""
        monkeypatch.setattr(
            nightly,
            "instrument",
            lambda name, args: QUIET if name == "friction" else {},
        )
        nightly.main([])
        assert nightly.LOG.exists()

    def test_friction_over_the_bar_stages_a_brief(self, staging, monkeypatch):
        monkeypatch.setattr(
            nightly, "instrument", lambda name, args: BUSY if name == "friction" else {}
        )
        assert nightly.main([]) == 0
        text = nightly.BRIEF.read_text()
        assert "windows-path-quoting" in text
        assert "reflect" in text

    def test_the_brief_forbids_merging(self, staging, monkeypatch):
        """The human review checkpoint replaces the numeric gate SkillOpt has
        and this loop cannot build, so it must be stated in the brief itself."""
        monkeypatch.setattr(
            nightly, "instrument", lambda name, args: BUSY if name == "friction" else {}
        )
        nightly.main([])
        assert "Do not merge" in nightly.BRIEF.read_text()

    def test_a_pending_brief_blocks_a_second_one(self, staging, monkeypatch):
        """One proposal per night, enforced by the unread brief itself."""
        nightly.BRIEF.write_text("last night, unreviewed")
        monkeypatch.setattr(
            nightly, "instrument", lambda name, args: BUSY if name == "friction" else {}
        )
        assert nightly.main([]) == 0
        assert nightly.BRIEF.read_text() == "last night, unreviewed"
        assert "held" in nightly.LOG.read_text()

    def test_a_broken_instrument_fails_loudly(self, staging, monkeypatch):
        monkeypatch.setattr(nightly, "instrument", lambda name, args: None)
        assert nightly.main([]) == 1
        assert not nightly.BRIEF.exists()

    def test_dry_run_writes_nothing(self, staging, monkeypatch):
        monkeypatch.setattr(
            nightly, "instrument", lambda name, args: BUSY if name == "friction" else {}
        )
        assert nightly.main(["--dry-run"]) == 0
        assert not nightly.BRIEF.exists()
        assert not nightly.LOG.exists()


class TestAuditIsStrict:
    def test_the_audit_is_invoked_with_strict(self, staging, monkeypatch):
        """A warn band is a prompt to a human in the room; an unsupervised run
        has none, so the nightly pass must keep the hard behaviour."""
        seen: dict[str, list[str]] = {}

        def record(name, args):
            seen[name] = args
            return QUIET if name == "friction" else {}

        monkeypatch.setattr(nightly, "instrument", record)
        nightly.main([])
        assert "--strict" in seen["audit_assets"]
