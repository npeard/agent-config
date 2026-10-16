"""Contract tests for hooks/plain-math.py, run as a JSON filter subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "plain-math.py"


def run(payload: dict) -> str:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def edit(path: Path, **tool_input) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path), **tool_input}}


def test_written_file_with_stand_ins_blocks_with_each_finding(tmp_path):
    path = tmp_path / "report.typ"
    path.write_text("Loop phase phi.\n\nAt 3pi/2 too.\n", encoding="utf-8")
    out = json.loads(
        run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(path), "content": ""},
            }
        )
    )
    assert set(out) == {"decision", "reason"}
    assert out["decision"] == "block"
    assert '1:12: greek: "phi" -> $phi$' in out["reason"]
    assert '3:4: pi-multiple: "3pi/2" -> $3pi/2$' in out["reason"]


def test_edit_blocks_only_on_lines_it_wrote(tmp_path):
    path = tmp_path / "fig.py"
    path.write_text(
        "import matplotlib\nax.set_title('rho')\nax.set_xlabel('time')\n",
        encoding="utf-8",
    )
    assert run(edit(path, new_string="ax.set_xlabel('time')")) == ""
    out = json.loads(run(edit(path, new_string="ax.set_title('rho')")))
    assert '2:14: greek: "rho"' in out["reason"]


def test_untouched_findings_are_counted_not_listed(tmp_path):
    path = tmp_path / "a.tex"
    path.write_text("phi here\nnew phi\n", encoding="utf-8")
    reason = json.loads(run(edit(path, new_string="new phi")))["reason"]
    assert "2:5" in reason and "1:1" not in reason
    assert "1 more elsewhere in the file" in reason


def test_clean_unrelated_or_broken_files_are_silent(tmp_path):
    clean = tmp_path / "ok.typ"
    clean.write_text("Loop phase $phi$.\n", encoding="utf-8")
    broken = tmp_path / "broken.py"
    broken.write_text("import matplotlib\ndef (:\n", encoding="utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text("phi\n", encoding="utf-8")
    for path in (clean, broken, notes, tmp_path / "missing.typ"):
        assert (
            run(
                {
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(path), "content": ""},
                }
            )
            == ""
        )
    assert run({"tool_input": "not a dict"}) == ""
