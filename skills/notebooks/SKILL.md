---
name: notebooks
description: Use when creating, editing, executing or writing up a Jupyter notebook (.ipynb) - covers which tool to reach for, how to find the notebook MCP server that no config file lists, and what belongs in markdown prose versus cell output.
compatibility: Cell tools need either the notebook MCP server (a VS Code extension, dynamic localhost port) or the host's own NotebookEdit; execution and kernel inspection need the MCP server specifically.
---

# Notebooks

A notebook is a thing the user will edit after you. Write it so their
next change does not invalidate your prose, and reach for the tools that
exist rather than hand-authoring JSON.

## Tool precedence

| Task                                     | Tool                                                                                                                                                    |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| List, outline, search, read a cell       | `notebook_list_open`, `notebook_get_outline`, `notebook_search`, `notebook_get_cell_content`                                                            |
| Create, edit, move, delete cells         | `notebook_insert_cell`, `notebook_bulk_add_cells`, `notebook_edit_cell`, `notebook_move_cell`, `notebook_delete_cell` -- else the host's `NotebookEdit` |
| Execute and read results                 | `notebook_run_cell`, then `notebook_get_cell_output`                                                                                                    |
| Live kernel variables, execution history | `notebook_get_kernel_context`, `notebook_get_kernel_info`                                                                                               |
| Strip outputs                            | `notebook_clear_outputs`, `notebook_clear_all_outputs`                                                                                                  |
| Write or edit raw `.ipynb` JSON          | **Never**                                                                                                                                               |

The last row is the rule that costs the most when broken. A measured
baseline: one notebook authored by emitting nbformat JSON, executed via
`nbconvert`, then re-read by parsing the file with `json` to paste
results back, took **823 tool calls and 278k tokens**. The MCP path is
the same work in a handful of calls, because `notebook_run_cell` returns
the output you would otherwise re-parse the file to get.

Two capabilities have no `NotebookEdit` equivalent, and they are why the
MCP server is worth finding: **executing a cell** and **reading live
kernel state**. Without them you cannot check your own work, which is
what pushes an agent toward asserting results in prose.

### Do not build a third path

Writing a Python script that emits the notebook -- then deleting the
script -- is the same defect as writing the JSON by hand, plus an
artifact the user never asked for. If the cell tools are unavailable,
say so and ask; do not invent a generator.

## Finding the MCP server

It is registered in **no** configuration file. Searching
`~/.claude.json`, `settings.json`, `.mcp.json` or
`claude_desktop_config.json` finds nothing and proves nothing -- a
research pass concluded "no Jupyter MCP server exists on this machine"
from exactly those searches while the server was live and serving 16
tools.

It is an HTTP endpoint published by a VS Code extension
(`notebook-mcp-server`) on a **dynamic localhost port**. To find it:

1. Check whether `notebook_*` tools are already available to you. If
   they are, stop -- you have it.
2. Read the extension's output channel in VS Code, which prints
   `Notebook MCP Server activated at http://127.0.0.1:<port>/mcp`.
3. Probe for a listener and confirm with an MCP `initialize` call.

```bash
# The port changes between sessions -- never hardcode one.
netstat -ano | grep LISTENING | grep 127.0.0.1
curl -s -X POST http://127.0.0.1:<port>/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
       "protocolVersion":"2024-11-05","capabilities":{},
       "clientInfo":{"name":"probe","version":"1"}}}'
```

A `serverInfo.name` of `notebook-mcp-server` confirms it. Three
outcomes, and the middle one is the common one:

- **`notebook_*` tools available.** Use them.
- **The port answers but no `notebook_*` tool is in your tool index.**
  The extension registered against a different VS Code window than the
  one backing this session. Report that specifically -- "the server is
  live on port N but not wired to this session" -- because "no MCP
  server" would send the user looking for the wrong problem. Fall back
  to `NotebookEdit` for cells, and say the smoke test could not run.
- **Nothing answers.** The extension is not running: ask the user to
  start it. VS Code owns its lifecycle; there is nothing for you to
  launch.

Never fall back to raw JSON in any of the three. `NotebookEdit` needs an
existing file, so a brand-new notebook does need a minimal nbformat
envelope (`cells: []` plus kernelspec) written once -- that is the one
sanctioned exception, and every cell after it goes through the tools.

Without an execution tool you cannot smoke-test. **Say so plainly and
leave the notebook un-executed** rather than asserting results you did
not see. `mcp__ide__executeCode` only reaches a notebook already open as
an editor tab, so it returns "No active notebook editor found" for a
file you just created.

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
| "No Jupyter MCP is configured, so there isn't one"          | No config lists it. Probe the port.                                           |
| "I'll just write the .ipynb JSON, it's one file"            | Measured at 823 calls and 278k tokens. Use the cell tools.                    |
| "I'll write a script to generate the notebook"              | A third path, plus an artifact nobody asked for.                              |
| "The user asked to see the results, so I'll write them up"  | Results live in cell output. Write the reading guide; report numbers in chat. |
| "I'll note that these numbers are from a particular config" | That note is the defect. Delete the numbers.                                  |
| "I'll add a caveat that the table may be stale"             | You already know it's wrong. Delete it.                                       |
| "These constants should be in a shared module"              | Not in a notebook. The user needs to reach them.                              |
