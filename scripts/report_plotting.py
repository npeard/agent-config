"""CLI and output plumbing for the figure scripts of a `new-report` scaffold.

Imported, not copied, by each `figures/plot_*.py`, so a fix here reaches every
report at its next agent-config bump. Style stays in the consumer's scripts.
Stdlib only: `save` calls the figure's own method, so this module never needs
matplotlib to import.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_cli(doc: str, argv: list[str], flags: tuple[str, ...]) -> argparse.Namespace:
    """Parse one required path per flag, with the script's docstring as help."""
    parser = argparse.ArgumentParser(
        description=doc, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    for flag in flags:
        parser.add_argument(flag, required=True, type=Path)
    return parser.parse_args(argv)


def save(fig, output: str | Path) -> None:
    """Write `fig` to `output`, creating its directory for a run by hand."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
