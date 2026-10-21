---
name: compute-job-safety
description: Use when starting, stopping, restarting, or diagnosing a long-running compute job, including GPU, cluster, batch, simulation, or background workloads that may consume shared resources or write durable outputs.
compatibility: Requires access to the job's process, scheduler, or project-local driver; host lifecycle hooks can warn about interruption but cannot safely identify arbitrary jobs.
---

# Compute job safety

Treat an interrupted compute job as potentially still running and its
output as potentially partial. Do not relaunch or consume its results
until that is resolved.

| Signal                      | Safe interpretation                 | Required next action                                       |
| --------------------------- | ----------------------------------- | ---------------------------------------------------------- |
| Wrapper stopped             | Descendants may still run           | Check the owned PID, process group, or scheduler ID.       |
| Output missing or smaller   | Partial write, not a smaller result | Validate logs/checkpoints before deleting or consuming it. |
| Same output requested again | A concurrent writer may exist       | Refuse or inspect the known peer before relaunching.       |

## Before starting

- Identify the job's ownership boundary: process group, PID file,
  scheduler job ID, or project driver. Do not infer ownership from a
  broad process-name match when legitimate concurrent work may share it.
- Check whether that identified job is already live. If it is, inspect
  or resume it rather than starting a competing writer.
- Determine the durable outputs and whether the program overwrites,
  truncates, appends, checkpoints, or writes a temporary file before
  publishing a result.

## Long jobs: launch detached and return

A subagent that starts a job expected to outlast a few minutes launches
it detached, records the PID, log, and output path, and returns "waiting
on <job>, output at <path>, done when <condition>". The orchestrator
waits once (`run_in_background` or Monitor) and dispatches a fresh,
small agent to consume the result. Why: a waiting agent pays for its
whole context on every wake-up, and the orchestrator waiting in the
background pays nothing. `hooks/poll-guard.py` denies a subagent's
sleep-poll loop and points here. Worked case: `examples.md` 1.

## Resource allocation

- **Dense networks train on the GPU, always.** Check the device and fail
  loudly if it is absent; never fall back to CPU silently. Why: agents
  have trained dense networks on CPU for no reason (examples 3 and 4).
- **CPU use stays at or under 50% of logical cores at all times**,
  counted as processes x threads per process across everything the
  session has running, not per job. Set thread counts explicitly (BLAS
  and OpenMP variables, `torch.set_num_threads`, a pool's `max_workers`)
  instead of inheriting a library default of all cores. The exception is
  a PyTorch parallel training run on CPU, which should be rare; say so
  when choosing it. Why: 48 processes on 32 cores starved the machine
  (examples 2 and 3).
- **Answer for the machine, not only the task.** Before starting
  compute, state what the job will occupy (cores, threads, GPU memory,
  duration) and who else shares the machine: supervising agents, other
  sessions and projects, the user. A job that finishes sooner by
  starving them has not saved time. This forbids taking over the
  machine, not using the budget: the full 50% for a job that needs it is
  correct.

## After interruption or failure

1. Check the known process group, PID, or scheduler job ID for
   survivors. A stopped shell wrapper does not prove its descendants
   stopped.
2. Do not relaunch while an owned survivor can still write the same
   output. Stop it through the driver or scheduler when possible;
   escalate rather than killing an ambiguously owned process.
3. Treat missing, shrunken, truncated, or newly modified output as
   partial until validated. Never describe it as a smaller valid result
   by default.
4. Check logs, checkpoints, and the job's own completion signal before
   using or deleting any result.

## Make the project safe

Project-local drivers, not this shared skill, should implement the
mechanism:

- write to a temporary path and atomically rename only validated
  completion;
- record a PID/process group or scheduler job ID and clean up known
  children on `INT`/`TERM`;
- refuse a second writer for the same declared output;
- make destructive restart options explicit rather than defaulting to
  them.

Use host interruption hooks only as a reminder or marker to run the
recovery check. They normally lack reliable child-process identity, may
not fire for subagents, and must not indiscriminately terminate compute
processes.

## Boundary

Keep scheduler commands, GPU-memory tactics, output formats, and
scientific validation rules in the owning project. This skill supplies
the safety invariant; the project supplies the process identity and
recovery procedure.
