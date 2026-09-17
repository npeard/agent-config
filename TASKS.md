# agent-config Tasks

Cross-project agent tooling work. One entry per durable change; delete
an entry when its change lands.

______________________________________________________________________

## Notebook MCP: propagate what the 2026-09-16 doqs session learned

Filed 2026-09-16 from a session in `~/Documents/doqs` (branch
`workbench-hygiene-shots`). That session spent a large fraction of its
budget failing to edit two Jupyter notebooks, and the findings are
general, not doqs-specific. **Read that session's transcript for the
full detail before acting** -- what follows is enough to pick it up, not
a substitute for it.

### What happened, in brief

The `notebooks` skill points at `notebook-mcp-server`, the VS Code
extension (`olavovieiradecarvalho.notebook-mcp-server`, v0.3.0 on the
machine in question). It was found live, registered with
`claude mcp add`, and **still could not do the job.** Three distinct
failures, in increasing order of severity:

1. **Requires a human-focused active notebook editor.** Every tool
   errors `No active notebook` unless a human clicks *into a notebook
   cell body* -- focusing the editor tab is not enough. The
   `notebook_uri` parameter is advertised on most tools and is
   **ignored**: the server rejects on "no active notebook" before it
   reads the argument. Clicking into a cell did eventually work, and
   that specific trick is worth recording in the skill.
2. **Session instability.** The MCP client session expired three times
   in roughly an hour, twice mid-edit, each time requiring a full Claude
   Code restart to reconnect. The HTTP endpoint stayed healthy (200)
   throughout -- it is the client session that dies, so probing the port
   says nothing about whether the tools are usable.
3. **Writes never reach disk.** `notebook_edit_cell` returned
   `{"updated": true}` for two cells; `git status` stayed clean and
   `grep` found neither edit in the file. It had mutated VS Code's
   in-memory buffer only, and persisting required a human pressing
   Ctrl+S. **This is the disqualifying one**: an agent cannot verify its
   own work through a channel that reports success without writing
   anything.

A second, independent blocker compounded it: the host's `Read` tool
refuses large notebooks outright
(`File content (28328 tokens) exceeds maximum allowed tokens (25000)`),
and `offset`/`limit` do not help because the tool renders the whole
notebook before slicing. Since `NotebookEdit` requires a prior
successful `Read`, **`NotebookEdit` is structurally unusable on any
notebook above the ceiling** -- which is most real research notebooks.
The skill currently presents `NotebookEdit` as the fallback when MCP
tools are unavailable; on these files there was no working path at all.

### What to change

**1. `skills/notebooks/SKILL.md`.**

- Record the click-into-a-cell requirement and the ignored
  `notebook_uri`, under the existing "port answers but no tool in your
  index" material -- the current three outcomes do not cover "tools
  present, every call rejected for lack of focus."
- Add the buffer-versus-disk distinction as a first-class check. The
  rule to state: after any MCP cell edit, confirm the change reached
  disk (`git status`, or re-read the file) before believing it. A tool
  returning `updated: true` is not evidence.
- Fix the `NotebookEdit` fallback advice to acknowledge the Read token
  ceiling, and say what to do when both paths are closed.
- Switch the recommended server. Datalayer's `jupyter-mcp-server`
  (https://github.com/datalayer/jupyter-mcp-server, BSD-3, v2.1.16)
  talks to a Jupyter server's kernel and contents APIs rather than an
  editor buffer, so it structurally avoids all three failures: no focus
  requirement, no human save step, no VS Code extension host. **This is
  now verified, not researched**: the doqs session used it to edit and
  insert cells in a 41-cell notebook, confirmed every write on disk with
  `git status`, executed cells against the correct pixi interpreter, and
  committed the result. The kernel-binding bug cluster (issues #425,
  #438) did not bite -- launching the server from inside the target env
  leaves exactly one kernel, so there is nothing to mis-bind.
- **The recipe, with the two things that were not obvious.** Launch
  `jupyter lab --no-browser --port 8889 --IdentityProvider.token <tok> --ServerApp.root_dir <repo>`
  from inside the project's pixi env, then
  `claude mcp add jupyter --scope local --env JUPYTER_URL=... --env JUPYTER_TOKEN=... -- uvx jupyter-mcp-server@latest start --transport stdio`.
  1. The **`start --transport stdio` suffix is required**. A bare
     `uvx jupyter-mcp-server@latest` serves nothing and the connection
     times out at 30s; the CLI needs a subcommand. The first `uvx` run
     also times out while it downloads, so pre-warm it.
  2. **Launch the Jupyter server detached** (`Start-Process` on
     Windows), not as a child of the agent session. A session-child
     process dies on every restart, and each restart then needs a manual
     relaunch before the MCP server can connect to anything.
     `pixi-kernel` is **not** needed when the server is launched from
     within the target env: the env's own kernelspec uses a bare
     `python`, which resolves to the pixi interpreter. The project must
     have `jupyter-collaboration` installed -- cell reads and edits go
     through `/api/collaboration`, which 404s without it, while code
     execution keeps working, so the failure looks like a permissions
     problem rather than a missing package.
- **Record its one sharp edge.** `insert_cell` silently drops cells when
  called several times in quick succession: three back-to-back inserts
  each returned success with a rising cell count, and none reached disk
  or survived in the server's own view. One insert at a time, with a
  disk check before the next, worked for five consecutive cells.
  `overwrite_cell_source` / `edit_cell_source` on existing cells never
  showed this. Same shape as the VS Code extension's failure -- which is
  the general lesson for the skill: **on any notebook MCP server, a
  success return is not evidence the write landed.**

**2. `scripts/toolgaps.py`.**

This is the right home by its own stated boundary -- absent capability,
not repo state. A project containing `.ipynb` files has a tooling need
that is invisible until something looks for it: a *working* agent-facing
notebook channel. Suggested check: if the project has notebooks, report
whether any notebook MCP server is registered for it, and whether the
notebooks exceed the host `Read` ceiling (which silently disables
`NotebookEdit`). The asset to point at is whatever the skill settles on
above.

Consider also reporting `jupytext` as absent-but-idiomatic when a repo
has notebooks. The research called it the standard answer to notebooks
in version control, and it pairs a `.ipynb` to a `.py:percent` file that
ordinary text tools can edit -- which would have made this entire
session a non-event. It costs little in a repo that already strips
outputs with `nbstripout`. It was deliberately *not* adopted in doqs
mid-task because it changes a repo's notebook workflow and deserves its
own decision.

**3. `scripts/preflight.py`.**

Lighter touch, and possibly nothing. Preflight owns "is this repo fit to
work in right now." If a session is about to do notebook work, a dead
MCP client session is exactly that kind of state -- but preflight cannot
know the session's intent, and probing the HTTP port is affirmatively
misleading here (the endpoint returned 200 through all three client
deaths). If anything goes in, it should check for a *usable* channel,
not a listening port. Decide whether that is knowable cheaply; if not,
leave preflight alone and let `toolgaps` carry it.

### Bar check

This is four-plus hours of one session lost to a documented-but-wrong
recommendation in an always-loaded-on-demand skill, and the same skill
will send the next session down the same path. That clears the bar for
changing the skill. The `toolgaps` addition is a judgement call -- weigh
it with `reflect` rather than assuming it is warranted.
