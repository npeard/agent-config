# Local coding agent: research findings and pathways

Status: research complete, nothing built, no pathway approved.

This records a brainstorming session held 2026-09-11 into hosting a
local coding model on this workstation, to use alongside Claude Code or
independently. It exists so a later session can resume without
re-running the research or re-deriving the cost argument. Findings were
gathered by web research (dated below, and this field moves fast) and
from this repository's own `pixi run burn` measurements.

The headline conclusion: the originally imagined project -- a local
model doing agentic coding work to dilute Claude token costs -- is aimed
at the wrong cost. A narrower project aimed at context reduction is well
supported by the measured data. Read "Why the obvious framing fails"
before reviving the original framing.

## Hardware

Measured on this box 2026-09-11:

| Device          | VRAM  | Role                                     |
| --------------- | ----- | ---------------------------------------- |
| RTX 3090 Ti     | 24 GB | Research and simulation compute, primary |
| Quadro RTX 4000 | 8 GB  | Idle at time of measurement              |

Free disk: 177 GB of 932 GB. A 30B-class model at 4-bit is roughly 18
GB, so disk is not a constraint.

Two facts that shaped the discussion:

- The 3090 Ti is a research instrument first. The stated preference is
  to start the model server manually, per session, so it never holds
  VRAM that simulation work needs. Every integration must therefore
  treat "endpoint is down" as the normal case rather than an error.
- The idle Quadro RTX 4000 is a real option. A smaller model pinned to
  the 8 GB card could serve summarization without ever competing for the
  card that matters. This was raised but not explored.

Correcting two premises from the original question: llama.cpp is not
CPU-only, it has full CUDA support and is the standard way to run a
quantized model on a single consumer GPU; and HuggingFace `transformers`
is a runtime as well as a model library, though not the one to use for
serving here. The GPU is decisive: CPU-only inference of a useful coding
model runs at a few tokens per second, which is unusable for agentic
loops.

## Why the obvious framing fails

From `pixi run burn`, window 2026-08-13 onward, 24 sessions:

```
cost $3657.02  =  orchestrator $2649.71  +  subagents $1007.31 (28%)

orchestrator tokens by kind:
  cache_read    3833.0M
  cache_write     55.2M
  output           7.6M
  input           26.1k
```

Cache-read exceeds output by roughly 500 to 1. The money goes to
re-reading accumulated context on every turn, not to generating tokens.
The context-tax curve in the same report shows a last-decile session
costing 3.7 times the first per turn, for the same work, purely because
context grew.

So having a local model *generate* code attacks the 7.6M output side --
a fraction of a percent of the ledger. Even perfect offloading of all
locally-suitable generation would barely move $3657.

Two further findings independently sink the supervised-agent idea on
this hardware:

- **Tool-call reliability compounds.** The best community figure for a
  30B-class model is about 96 percent well-formed tool calls. Over a
  50-turn session that is 0.96^50, roughly 13 percent. Per-turn
  benchmark parity does not survive an agentic session.
- **The supervision cost is the operator.** In the controlled
  head-to-head cited below, on the same VRAM class, the local model
  needed 7 operator interventions against Claude's 1, and produced 74
  passing tests against 114. Since the manual-start constraint already
  establishes that operator time is the scarce resource here, a workflow
  that multiplies interventions by 7 is the wrong trade.

## What the data does support

The expensive, addressable thing is raw read-only output entering
Claude's context. Also from `burn.py`:

```
orchestrator bash: 1820 read-only, 3709 acting
read-only shell output is 50% of tool output entering context
of 1820 read-only results: median 996 chars, p90 3.7k, p99 15.8k,
  largest 29.6k
one read-only result averages 1774 chars; keeping it costs roughly
  $0.022 over 100 further turns
  $0.067 over 300 further turns
```

A local model that reads a 25 000-character file and returns a
500-character summary means those 25 000 characters never enter Claude's
context and are never cache-read again. This is the right target for
three reasons:

1. It attacks the 3833M cache-read side, which is where the cost is.
2. Summarization and short-text classification are where a 24 GB model
   is closest to frontier capability. The gap on "summarize this file"
   is small; the gap on "implement this feature across five files" is
   the 7x-intervention gap.
3. The economics are unarguable. `burn.py` already computes that a haiku
   dispatch must replace 5 read-only calls to pay for itself, and a
   sonnet dispatch 60. A local dispatch costs nothing, so it breaks even
   on the first call, and it is worth using in the many places where
   even a haiku round trip is not.

Prompt-processing throughput matters more than generation here, and that
is the favorable direction: a 25 000-character file is about 7000
tokens, roughly 2 seconds to ingest at measured speeds.

This repository has two specific candidate tasks already instrumented:

- `scripts/friction.py` classifies error text with hand-written regexes,
  and its own comments describe the unclassified rate as measuring
  "classifier decay" as new failure shapes appear. Semantic
  classification of short text, low stakes, with `unclassified` already
  handled as a fallback.
- `scripts/burn.py` defines `is_delegable_read` -- "reading to
  understand, as opposed to acting" -- and already tracks the volume per
  session. It is both the target list and the measurement harness, so
  savings can be measured against a real baseline rather than estimated.

## Recommended stack

Researched 2026-09-11. Verify before building; this moves fast.

- **Model: Qwen3.6-35B-A3B** at UD-Q4_K_XL. A mixture-of-experts model
  with 35B total but only 3B active parameters, which is the whole
  reason it is usable: measured 140 tok/s generation and 3360 tok/s
  prompt processing on a single RTX 3090 at about 89 000 context, all
  layers on GPU. The dense Qwen3.6-27B scores 3.8 points higher on
  SWE-bench Verified (77.2 against 73.4) but runs roughly 6 times
  slower, in the low tens of tok/s. For many-turn work the MoE is the
  only interactive option.
- **Alternate: Devstral Small 2**, 24B dense, Apache 2.0, 68.0 on
  SWE-bench Verified. Worth keeping in reserve for its tool-calling
  reputation; Mistral quotes Cline describing its tool-call success rate
  as on par with the best closed models.
- **Runtime: llama.cpp built with CUDA**, `llama-server --jinja`.
  Measured CUDA against Vulkan on the same model: 3360 against 2787
  tok/s prompt processing, and CUDA needed fewer offloaded layers to
  reach full context. `--jinja` is required to use the GGUF's embedded
  chat template, and Qwen3-Coder emits a custom XML tool-call format
  rather than JSON, which needs llama.cpp's dedicated parser.
- **Optional front door: llama-swap** (MIT, single Go binary, ships
  Windows releases). Presents one OpenAI- and Anthropic-compatible
  endpoint and hot-swaps models per request with idle timeouts. Useful
  at 24 GB where two models cannot be co-resident.

### Platform hazards

- **Disable the NVIDIA "Sysmem fallback policy"** for the inference
  process. Windows WDDM silently spills GPU allocations into system RAM
  instead of failing, and every spilled access crosses PCIe at roughly a
  30-fold bandwidth penalty. Since decode is memory-bandwidth-bound,
  modest spill produces a mysterious 10-fold slowdown where Linux would
  give a clean out-of-memory error. This is the single most likely cause
  of a confusing result.
- **vLLM has no native Windows support** and no public roadmap for it.
  Options are WSL2 (which costs about 1.3 GiB of invisible GPU overhead,
  material when fighting for context), Docker Model Runner with a WSL2
  backend, or a community fork. Not recommended here.
- **Ollama has two traps**: its OpenAI compatibility layer omits
  `tool_choice`, and it defaults to a 2-4K context while agents need 32K
  or more. The latter is the documented cause of harnesses silently
  looping.
- **Context headroom can beat quantization fidelity.** In the
  head-to-head below, Q4 scored *worse* than Q3 on planning, 4.8 against
  6.3, because the larger quant left less room for context and triggered
  more compaction. Do not assume a higher quant is better at 24 GB.

### Capability gap, measured

A controlled head-to-head on an RTX 4090 24 GB, the same VRAM class as
the 3090 Ti, running local models in opencode against Claude Opus 4.7 in
Claude Code, on a real Playwright suite for a Laravel application:

| Metric                 | Claude Opus 4.7 | Qwen3.6-27B Q3 |
| ---------------------- | --------------- | -------------- |
| Plan score (of 10)     | 9.8             | 6.3            |
| Operator interventions | 1               | 7              |
| Context compactions    | 0               | 4              |
| Tests authored         | 203             | 140            |
| Tests passing          | 114             | 74             |

Local plans "hallucinated selectors" and "contradicted constraints". The
author's verdict: what a single 24 GB card buys for agentic coding is
"genuinely impressive, and not yet a daily driver against the cloud".
Named failure modes were constraint compliance, looping on errors, and
the absence of parallel subagents.

On benchmarks the gap looks smaller than it is: Qwen3.6-27B at 77.2
against Claude Opus 4.7 at 87.6 on SWE-bench Verified. SWE-bench is
single-issue work under a scaffold. The table above is what the same gap
looks like over a multi-turn session. Note also that the comparison
understates the current gap, since Anthropic's line has moved on since
Opus 4.7.

Structural advantages no local 24 GB setup replicates: parallel
subagents with isolated contexts returning only distilled summaries, and
a 1M context window against roughly 56-89K.

## Pathways

### A. Context-reduction service (recommended)

Scope the local model to one job: read and summarize, so raw file and
search output never enters Claude's context. Integrates into this
repository as a skill plus a hook, with `burn.py` as the measurement
harness against an existing baseline.

Why this one: it attacks the cost that the measurements actually show;
it uses the local model only where its capability is closest to
frontier; it fits the manual-start constraint without special handling,
since a missing endpoint simply falls back to a normal read; and it is
small enough to finish and evaluate quickly.

Success criterion, decided before building: a measurable reduction in
read-only characters entering context, visible in `pixi run burn`
against the pre-change baseline recorded above.

### B. Staged ladder, each rung gated on measurement

Pathway A as phase one; build the supervised-agent rung only if measured
savings justify it. The four goals originally stated -- offload cheap
work, dilute cost under supervision, run fully independently, and learn
by doing -- do nest into one capability ladder on shared infrastructure.
The honest expectation is that phase two fails its gate on the
compounding math above, so the value of writing B down is mostly that it
names the gate rather than leaving the ladder implicit.

### C. Independent-agent playground (optional, separate repo)

A full local stack -- llama-swap plus opencode or Cline -- optimized for
offline work, privacy-sensitive code, and usability when rate-limited.
Makes no cost claim at all, which is what makes it honest. This is the
pathway that serves the learning goal.

Keep this in its own repository. Model weights, serving configs, and
experiments are not cross-project agent configuration, and a research
playground should not be able to destabilize the daily config. A and C
do not conflict and could run in parallel.

### Repository layout

Recommendation: pathway A belongs in `claude-config`, since a
summarization skill plus a hook plus `burn.py` measurement is agent
configuration in exactly this repository's sense. Pathway C belongs in a
separate repository for the reasons above.

## Resuming this work

Open questions, none of them answered yet:

- Which pathway, if any, to pursue. Nothing is approved.
- Whether to serve the summarization model from the idle Quadro RTX 4000
  rather than the 3090 Ti, sidestepping contention entirely. This was
  raised and not explored; the 8 GB limit implies a much smaller model,
  so the capability trade is unmeasured.
- Whether `friction.py` classification or read-and-summarize is the
  better first target under pathway A.

Before building anything, re-run `pixi run burn` to refresh the
baseline, and re-verify the model and runtime recommendations: research
here is dated 2026-09-11 and every part of this stack moves quickly.

Sourcing caveat worth carrying forward: most search results on this
topic are content farms publishing confident VRAM tables and benchmark
numbers with no methodology, which frequently contradict each other. The
numbers above come from first-party model cards, project documentation,
or named benchmark write-ups. Two things could not be verified and
should be treated as unreliable: Qwen's own blog renders as
JavaScript-only and could not be fetched (benchmarks were confirmed from
HuggingFace model cards instead), and the Aider polyglot leaderboard is
stale, topping out in 2025 -- any 2026 Aider polyglot number quoted for
a recent model did not come from Aider.

### Key sources

- Qwen3.6-35B-A3B model card:
  <https://huggingface.co/Qwen/Qwen3.6-35B-A3B>
- Qwen3.6-27B model card: <https://huggingface.co/Qwen/Qwen3.6-27B>
- Devstral 2: <https://mistral.ai/news/devstral-2-vibe-cli/>
- llama.cpp function calling:
  <https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md>
- llama-swap: <https://github.com/mostlygeek/llama-swap>
- Single-3090 MoE benchmarks:
  <https://www.gilesthomas.com/2026/07/benchmarking-qwen-3-6-35b-moe-rtx-3090>
- Local against Claude head-to-head:
  <https://johnhringiv.com/claude-vs-local>
- Cline local-model guidance: <https://cline.bot/blog/local-models>
- Sysmem fallback fix:
  <https://runaihome.com/blog/shared-gpu-memory-slow-local-ai-sysmem-fallback-fix-2026/>
