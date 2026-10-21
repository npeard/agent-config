---
name: auto-research
description: Use when about to propose a new model, method, fit function or explanation because results look poor, or when driving an open-ended research question such as "why is this fit poor" or "find a better estimator". Sits above workflow-orchestration and writing-orchestration, and demands evidence of which current assumption fails before anything new is tried.
compatibility: Hands kept code to workflow-orchestration and prose to writing-orchestration.
---

# Auto-research

When you hear hooves, think horses, not zebras. A poor result is far
more often the current approach failing in a mundane way -- a bad
starting regime, a wrong parameter -- than evidence that the system
needs a new model. So before proposing a new or modified approach,
understand with evidence why the current one is failing. A creative
explanation offered first costs a build-and-evaluate cycle on an idea
the data never asked for, and the real fault survives it (example 1).

**The boundary.** `superpowers:systematic-debugging` finds why code
misbehaves; auto-research finds why a model or method misfits the world.
When the evidence points at a code defect, switch to that skill.

## The loop

1. **Revisit the assumptions.** List what the current approach assumes
   about the system -- functional form, parameter regime, starting
   values -- and question from first principles whether each is valid.
2. **Find which assumption is wrong, and show it.** Look before
   theorizing: plot the fit against the data, read the residual, compare
   fitted parameters with what first principles predict. Support the
   conclusion with empirical evidence and say which assumption is
   incorrect, if any, and why.
3. **Only then try the new approach.** Make the change the evidence
   points to, then measure against the current approach whether it is
   actually better -- and if not, why. Repeat from step 1.

Do not get creative in devising new approaches or explanations until
steps 1 and 2 are done.

## Handing off

This skill owns the question, not the build. When a step needs kept code
-- a new fitting routine, a sweep, a benchmark -- run it under
`workflow-orchestration`; when it needs a write-up, under
`writing-orchestration`. Step 3's measurement is that spine's success
metric: a goodness of fit, a residual, an error against the current
approach as baseline.

## Red flags

| Thought                                  | Reality                                                                              |
| ---------------------------------------- | ------------------------------------------------------------------------------------ |
| "The fit is poor, so the model is wrong" | Or the fit is stuck in a bad regime. Plot it over the data first.                    |
| "The data seem to show X changing"       | Measure X before building a model around it.                                         |
| "A more flexible model fits better"      | A time-varying envelope would have absorbed the too-small amplitude, not exposed it. |
| "The new approach looks better"          | Better than the current one, by which number? And if not, why not?                   |
