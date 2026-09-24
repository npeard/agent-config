# agent-config Tasks

Cross-project agent tooling work. One entry per durable change; delete
an entry when its change lands.

______________________________________________________________________

## Notebooks: toolgaps and preflight follow-ups

Filed 2026-09-16 from doqs sessions 3d220b2c and 1619c6cc. The
`notebooks` skill now recommends Datalayer's `jupyter-mcp-server` and
records its recipe and failure modes, and `vscode-extensions.toml`
forbids the VS Code `notebook-mcp-server`. Two follow-ups remain, both
judgement calls to weigh with `reflect` rather than assume:

**1. `scripts/toolgaps.py`.** By its own boundary (absent capability,
not repo state), this is the natural home. A project containing `.ipynb`
files needs a working agent-facing notebook channel, and that need is
invisible until something looks for it. Suggested check: when notebooks
exist, report whether a `jupyter` MCP server is registered for the
project (`claude mcp list` from the project root), whether
`jupyter-collaboration` is a dependency (cell reads and edits 404
without it), and whether any notebook exceeds the host `Read` ceiling,
which silently disables `NotebookEdit`. Consider also reporting
`jupytext` as absent-but-idiomatic: pairing a notebook with a
`.py:percent` file makes it editable by ordinary text tools. It changes
a repo's notebook workflow, so it deserves its own decision per project.

**2. `scripts/preflight.py`.** Possibly nothing. A usable notebook
channel is state, but preflight cannot know the session intends notebook
work, and a listening port is not evidence of a usable channel (the VS
Code server answered 200 through three dead client sessions). Add a
check only if a *usable* channel is knowable cheaply; otherwise leave it
to `toolgaps`.
