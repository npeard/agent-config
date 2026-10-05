"""Canonical installer inputs shared by the host adapters and preflight."""

from __future__ import annotations

from pathlib import Path

GUIDANCE_NAME = "AGENTS.md"
CODEX_HEADER = "<!-- Generated from {source}; rerun this repository's installer to refresh. -->\n\n"


def canonical_guidance(repo: Path) -> str:
    return (repo / GUIDANCE_NAME).read_text(encoding="utf-8")


def claude_stub(repo: Path) -> str:
    return f"@{(repo / GUIDANCE_NAME).as_posix()}\n"


def codex_snapshot(repo: Path) -> str:
    source = (repo / GUIDANCE_NAME).as_posix()
    return CODEX_HEADER.format(source=source) + canonical_guidance(repo)


def instruction_adapters(repo: Path, home: Path) -> tuple[tuple[Path, str], ...]:
    return (
        (home / ".claude" / "CLAUDE.md", claude_stub(repo)),
        (home / ".codex" / "AGENTS.md", codex_snapshot(repo)),
    )


def skill_destinations(home: Path) -> tuple[Path, Path]:
    return (home / ".claude" / "skills", home / ".agents" / "skills")


def repo_link(home: Path) -> Path:
    """The stable locator for the checkout the installer ran from."""
    return home / ".agents" / "agent-config"
