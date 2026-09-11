---
name: compute-job-safety
description: Use when starting, stopping, restarting, or diagnosing a long-running compute job, including GPU, cluster, batch, simulation, or background workloads that may consume shared resources or write durable outputs.
compatibility: Requires access to the job's process, scheduler, or project-local driver; host lifecycle hooks can warn about interruption but cannot safely identify arbitrary jobs.
---

# Compute job safety

Treat an interrupted compute job as potentially still running and its
output as potentially partial. Do not relaunch or consume its results
until that is resolved.

## Before starting

- Identify the job's ownership boundary: process group, PID file,
  scheduler job ID, or project driver. Do not infer ownership from a
  broad process-name match when legitimate concurrent work may share it.
- Check whether that identified job is already live. If it is, inspect
  or resume it rather than starting a competing writer.
- Determine the durable outputs and whether the program overwrites,
  truncates, appends, checkpoints, or writes a temporary file before
  publishing a result.

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
