---
name: notebooks
description: Use when creating, editing, executing or writing up a Jupyter notebook (.ipynb) - covers which tool to reach for, how to connect the Jupyter MCP server, how to confirm a cell edit actually reached disk, and what belongs in markdown prose versus cell output.
compatibility: Cell tools need Datalayer's jupyter-mcp-server connected to a JupyterLab server launched from the project's own environment. The host's NotebookEdit works only on notebooks small enough for Read, and cannot execute.
---

# Notebooks

A notebook is a thing the user will edit after you. Write it so their
next change does not invalidate your prose, and reach for the tools that
exist rather than hand-authoring JSON.

## Tool precedence

The server is Datalayer's `jupyter-mcp-server`. Its tools appear as
`mcp__jupyter__<name>`.

| Task                                | Tool                                                                        |
| ----------------------------------- | --------------------------------------------------------------------------- |
| Pick the notebook to work on        | `list_notebooks`, `use_notebook`                                            |
| Read the notebook or a cell         | `read_notebook`, `read_cell`                                                |
| Edit, move, delete cells            | `overwrite_cell_source`, `edit_cell_source`, `move_cell`, `delete_cell`     |
| Add a cell                          | `insert_cell`, or `insert_execute_code_cell`, **one at a time** (see below) |
| Execute and read results            | `execute_cell`                                                              |
| Live kernel state, scratch probes   | `execute_code`                                                              |
| Strip outputs                       | `clear_cell_output`                                                         |
| No server, notebook under Read size | The host's `NotebookEdit` (edit only, no execution)                         |
| Write or edit raw `.ipynb` JSON     | **Never**                                                                   |

The last row is the rule that costs the most when broken. A measured
baseline: one notebook authored by emitting nbformat JSON, executed via
`nbconvert`, then re-read by parsing the file with `json` to paste
results back, took **823 tool calls and 278k tokens**. The MCP path is
the same work in a handful of calls, because `execute_cell` returns the
output you would otherwise re-parse the file to get.

Two capabilities have no `NotebookEdit` equivalent, and they are why the
server is worth connecting: **executing a cell** and **reading live
kernel state**. Without them you cannot check your own work, which is
what pushes an agent toward asserting results in prose.

### A success return is not evidence the write landed

On every notebook MCP server met so far, a write tool has returned
success for an edit that never reached the file. After each write,
confirm it on disk before building on it: `git status`, a `grep` for the
new text, or the file's cell count.

- `insert_cell` called several times in quick succession returned
  success with a rising cell count, and **none** of the cells reached
  disk or survived in the server's own view. Insert one cell, confirm
  it, then insert the next. `overwrite_cell_source` and
  `edit_cell_source` on existing cells have not shown this.
- The VS Code `notebook-mcp-server` extension returned
  `{"updated": true}` for edits held only in the editor's unsaved
  buffer.

### Do not build a third path

Writing a Python script that emits the notebook -- then deleting the
script -- is the same defect as writing the JSON by hand, plus an
artifact the user never asked for. If the cell tools are unavailable,
say so and ask; do not invent a generator.

## Connecting the server

Check in this order:

1. **`mcp__jupyter__*` tools are in your tool index.** Call
   `list_notebooks`. If it answers, use the tools.

2. **The tools are listed but every call fails to connect.** The
   JupyterLab server they talk to is not running. It is started
   separately (step 3a), so a session restart does not bring it back.
   Ask the user to relaunch it, or relaunch it yourself, detached.

3. **No `mcp__jupyter__*` tools.** Run `claude mcp list` from the
   project root. Registrations are per project (local scope), so
   grepping a global config proves nothing about this project. If
   `jupyter` is absent, set it up:

   a. Start JupyterLab **detached** from the project's pixi environment,
   so it outlives the session:
   `jupyter lab --no-browser --port 8889 --IdentityProvider.token <tok> --ServerApp.root_dir <repo>`.
   On Windows use `Start-Process`. A server started as a child of the
   agent session dies at every restart.

   b. Register the MCP server:
   `claude mcp add jupyter --scope local --env JUPYTER_URL=http://localhost:8889 --env JUPYTER_TOKEN=<tok> -- uvx jupyter-mcp-server@latest start --transport stdio`.
   The `start --transport stdio` suffix is required: without the
   subcommand the server serves nothing and the connection times out at
   30 s. Run the `uvx` command once beforehand, because the first run
   downloads and also times out.

   c. Restart the session so the tools load.

Two prerequisites fail silently:

- **The project must depend on `jupyter-collaboration`.** Cell reads and
  edits go through `/api/collaboration`, which returns 404 without it.
  Code execution keeps working, so the failure looks like a permissions
  problem, not a missing package.
- **Launch JupyterLab from inside the target environment.** Its own
  kernelspec then resolves to the project's interpreter, and there is
  exactly one kernel, so nothing can bind to the wrong one.
  `pixi-kernel` is not needed.

### Not the VS Code extension

`notebook-mcp-server` (`olavovieiradecarvalho.notebook-mcp-server`) is
forbidden in `vscode-extensions.toml`, and preflight flags it if it is
installed and enabled.

- It edits the editor's unsaved buffer, so its writes reach disk only
  when a human presses Ctrl+S.
- Every tool call needs a human to click into a cell body, and it
  ignores its own `notebook_uri` argument.
- Its client session expired three times in an hour. Its port kept
  answering 200 throughout, so a listening port says nothing about
  whether it is usable.

### When the server is unavailable

`NotebookEdit` requires a prior successful `Read`. `Read` refuses any
file over its token ceiling (25000 tokens), and `offset`/`limit` do not
help, because the whole notebook is rendered before slicing. So
**`NotebookEdit` cannot touch most real research notebooks.** Check the
size before planning around it.

When neither path works, say so, name which one failed and why, and ask
the user. Do not fall back to raw JSON.

A brand-new notebook is the one sanctioned exception. `NotebookEdit`
needs an existing file, so write a minimal nbformat envelope once
(`cells: []` plus a kernelspec). Every cell after it goes through the
tools.

Without an execution tool you cannot smoke-test. **Say so plainly and
leave the notebook un-executed** rather than asserting results you did
not see.

## Markdown prose describes the method, never the run

Every number in a notebook has exactly one home: cell output. Prose that
states what a particular execution produced is stale the moment the user
changes a parameter -- which is the reason they opened the notebook.

<Bad>
```markdown
**What the sweep found:** measured infidelities were 0.50%, 0.63%,
0.83%, 0.56% and 0.95% (at R = 0.6, 0.8, 1.0, 1.3, 1.6 um) -- uniformly
low, but not a clean monotonic trend.
```
</Bad>

<Good>
```markdown
**What to look for:** whether infidelity trends with R, or is dominated
by per-run optimization noise at fixed `MAX_EPOCHS`. The printed table
and the left panel answer this; if the spread across radii is comparable
to the spread between reruns at one radius, the trend is noise.
```
</Good>

This bans more than tables of numbers. All of the following are claims
about one execution and do not belong in markdown:

- Measured values, in a table or in a sentence.
- The configuration a result came from ("outputs above are from the full
  `MAX_EPOCHS = 60` sweep, not the reduced smoke test").
- Whether a run converged, how long it took, or which attempt produced
  the stored outputs.
- A conclusion that only holds for the committed parameter values.

**A disclaimer is not a remedy -- it is the smell.** Writing "the table
above is regenerated on every execution, check it against the freshly
printed numbers" means you already know the prose is wrong. Delete the
numbers instead. Real notebooks on this machine carry exactly this hedge
and it did not save them: one has an eight-row results table whose
configuration matches **no** row the notebook is currently set up to
produce.

Report smoke-test numbers **in the session chat**, where the user can
confirm your run matched theirs and the message is addressed to someone
who was there.

### What does belong in markdown

- What the notebook is for, and what the reader should conclude.
- A knob table -- the parameters and their defaults. Stable inputs, not
  derived outputs.
- The method, and why this method: an equation, a reference, why not the
  obvious alternative.
- What to look for in the output, phrased so it stays true when the
  numbers change.

## Notebooks are the DRY carve-out

`CODING_STANDARDS.md` rule 12 is strict in core library code. Here it is
relaxed on purpose, because the user's next act is editing this file:

- **Keep physical parameters inline**, as uppercase constants with units
  in a trailing comment. A parameter imported from a helper is one the
  user cannot find and change.
- **Keep plot styling inline.** Figure size, colours and limits are what
  gets tuned; a shared theme module moves them out of reach.
- Do not "fix" a notebook by extracting its constants into a module.
  That is a regression in this layer even though it is an improvement in
  `src/`.

Core library code called *from* the notebook stays strict. The carve-out
covers the notebook's own cells.

## Carve-outs

A **bug reproducer** legitimately hardcodes the wrong values, because
the wrongness is the subject -- naming the bad gradient entry is the
point. A **committed example** that ships as documentation may pin
outputs deliberately, if the project says so. Neither licenses a results
table in an exploratory notebook.

Stored outputs are a project-level decision: several repos here wire
`nbstripout` into pre-commit. Follow the project's setting rather than
importing one.

## Red flags

| Thought                                                     | Reality                                                                       |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------- |
| "No Jupyter MCP is configured, so there isn't one"          | Registrations are per project. Run `claude mcp list` there.                   |
| "The tool said `updated`, so the edit is in"                | Not evidence. Check the file on disk before the next write.                   |
| "I'll just write the .ipynb JSON, it's one file"            | Measured at 823 calls and 278k tokens. Use the cell tools.                    |
| "I'll write a script to generate the notebook"              | A third path, plus an artifact nobody asked for.                              |
| "The user asked to see the results, so I'll write them up"  | Results live in cell output. Write the reading guide; report numbers in chat. |
| "I'll note that these numbers are from a particular config" | That note is the defect. Delete the numbers.                                  |
| "I'll add a caveat that the table may be stale"             | You already know it's wrong. Delete it.                                       |
| "These constants should be in a shared module"              | Not in a notebook. The user needs to reach them.                              |
