# Workflow orchestration worked cases

Numbered as `SKILL.md` cites them, continuing the cost-guard series that
starts in `compute-job-safety/examples.md`. Open the one case you are
acting on; reading this end to end buys nothing.

### 5. Resume after a session-limit reset

**What happened:** session 3ede61fe, 2026-10-20 16:01, the orchestrator:
"After the reset I'll message the same agent so it carries on from that
point instead of starting over." Four such resumes found a cold cache
and rewrote 373k, 516k, 610k and 722k tokens.

**What to do:** dispatch a fresh agent with the previous report file.

### 6. Fix rounds resumed into one agent

**What happened:** the same implementer grew from 44k to 366k context in
its first run, then about +100k per fix round across three resumed
rounds and one ad-hoc "one more addition" (+103k). The user stopped it
at 724k ("700k tokens in 1 minute?").

**What to do:** past the cap, dispatch a fresh fix agent with the
report, the findings and the diff range.

### 7. Whole test directories per fix

**What happened:** across five doqs sessions, fix and simplify agents
re-ran entire `examples/*/tests` directories; tests took 51-224 min per
session.

**What to do:** run the narrowest target that covers the change, and the
full suite once at step 5.

### 8. Shell call overhead

**What happened:** trivial Bash calls measured about 1.8 s against 30 ms
for Read, at 1.2-2.8k calls per session (36-85 agent-minutes).

**What to do:** batch independent commands into one call.
