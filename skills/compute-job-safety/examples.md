# Compute job safety worked cases

Numbered as the rules in `SKILL.md` cite them. Open the one case you are
acting on; reading this end to end buys nothing.

### 1. Polling a long compute from a large context

**What happened:** session 3ede61fe, 2026-10-20, implementer "Stage 3
Task 3 report computes" (Opus). It waited on hour-long computes with
`until ...; sleep 30` loops that ran into the ~590 s Bash timeout,
waking about every 10 minutes. Each wake found the prompt cache expired
and rewrote the whole context: 80 such turns above 100k context wrote
42.1M of its 43.3M cache-write tokens, and the agent peaked at 724,459
tokens over 592 turns. Same shape: bf2b0c84 (75 turns, 12.2M) and
6ada315c (43 turns, 10.5M).

**What to do:** launch detached, record PID, log, and output path, and
return "waiting on <job>, output at <path>, done when <condition>". The
orchestrator waits in the background and dispatches a fresh small agent
on completion.

### 2. 48 processes on 32 cores

**What happened:** doqs, 2026-10-20. This case comes from the user's
account, not a transcript. One session launched 48 Python processes and
slowed the whole machine, starving its own supervising agents and other
projects.

**What to do:** count processes x threads against 50% of logical cores
across everything running, and set thread counts explicitly.

### 3. 70 threads, GPU idle

**What happened:** doqs handoff, 2026-10-05. Three training figures ran
about 70 threads on 32 cores while the GPU sat idle. Orphaned processes
later deleted `.h5` outputs, and `RESUME=True` silently skipped work.

**What to do:** train dense networks on the GPU and fail loudly if it is
absent; for the orphans, follow the interruption rules in `SKILL.md`.

### 4. Dense network trained on CPU

**What happened:** recurring, from the user's account; no transcript is
cited. Agents trained dense networks on CPU for no reason.

**What to do:** use the GPU, or stop and say why not.
