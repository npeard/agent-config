# Coding standards

The single definition of the house rules. The master `AGENTS.md` lists
these by name as author-facing triggers and points here; `SKILL.md`
carries the review process and points here. Neither restates the
content, so there is one place to change a rule.

**Layering.** These are cross-project rules and travel with the skill. A
project's own `CODING_STANDARDS.md` or `CLAUDE.md` layers on top and
wins where the two disagree -- a project knows its own constraints
better than a general preference does.

**Two binding rules for a reviewer using this file:**

1. Project standards override anything here.
2. Skip whatever tooling already enforces. Formatting, import order,
   line length, trailing whitespace, spelling and non-ASCII are owned by
   ruff, codespell, mdformat and `check_ascii.py`. `suppressions.py`
   owns rule 2's "does the suppression say why", and `thresholds.py`
   owns rule 6's detection half -- run them rather than reading for
   either. A reviewer spending attention there duplicates a hook that
   cannot be forgotten.

Note the asymmetry with rule 7: never report formatting itself, but do
report an author who hand-fixed formatting instead of running the tool.

## 1. No hidden defaults at call sites

A default lets behaviour change silently without any call site noticing.

```python
# Flag: the call site reads as "no configuration", and is silently
# re-tuned whenever someone edits the signature.
def train(model, lr=3e-4, warmup=500): ...
train(model)

# Prefer: keyword-only, explicit at the call site.
def train(model, *, lr, warmup): ...
train(model, lr=3e-4, warmup=500)
```

Project-specific enforcement (e.g. a strict no-default-arguments rule
for config dataclasses) belongs in that project's own `CLAUDE.md`; this
is the general taste.

## 2. Fix lint and type errors; do not suppress them

A suppression stops the linter checking that line forever. Flag every
one the diff adds without a narrow, durable, written reason -- and flag
one the diff *touches* without attempting to remove.

```python
# Flag
result = eval(expr)  # noqa: S307

# Prefer: fix the cause
result = ast.literal_eval(expr)

# Or, if genuinely unavoidable, record why it is narrow and permanent
# noqa: S307 -- expr is a validated notation string, see NOTATION.md
```

## 3. No tests that assert a refactor happened

A test whose failure would only mean "someone moved a file" says nothing
about behaviour, and it locks the layout in place.

```python
# Flag
def test_legacy_solver_removed():
    assert not Path("src/old_solver.py").exists()

# Prefer
def test_solver_matches_analytic_solution():
    assert solve(problem) == pytest.approx(closed_form(problem))
```

## 4. No superseded implementation kept alive as an oracle

If the old code only still exists to be compared against, the comparison
proves consistency with something nobody trusts.

```python
# Flag
assert new_fft(x) == old_fft(x)  # old_fft retained solely for this

# Prefer: compare against a naive or library reference, and record in prose
# why the old approach was discarded
assert new_fft(x) == pytest.approx(numpy.fft.fft(x))
```

## 5. A benchmark baseline must do production's job

Otherwise the comparison is meaningless.

```python
# Flag: the baseline is handed work the fast path must do itself
H = build_hamiltonian(params)
bench(lambda: baseline_solve(H))
bench(lambda: fast_solve(params))  # rebuilds H every call

# Prefer: both rebuild, or neither does
```

## 6. Delete a flaky gate; do not loosen its threshold

A gate edited to keep passing trains everyone to ignore red.

```python
# Flag
assert elapsed < 2.5  # was 1.0, then 1.8, then 2.5

# Prefer: delete the timed gate, assert the structural invariant that
# actually encodes the intent, and record the measurement in prose
assert solver.matrix_rebuilds == 1
```

## 7. Never hand-fix what a tool owns

Flag hand-realigned whitespace, hand-sorted imports, hand-fixed
spelling. The correction is to run the project's own command
(`pixi run format`, `ruff check --fix`, `pre-commit run --all-files`),
not to make the edit.

If the same class of correction keeps recurring, the finding is that it
belongs in the CD workflow -- a check that cannot be forgotten beats a
habit that can.

## 8. Comments record the why

```python
# Flag
# increment i by one
i += 1

# Prefer: record a constraint, an invariant, a workaround
# +1 because the instrument's API treats the endpoint as inclusive
i += 1
```

The code already states what and how. A comment repeating it is a second
thing to keep correct, and it will drift.

## 9. No speedup claimed from profiler percentages alone

cProfile's per-call bookkeeping inflates the apparent cost of small,
high-frequency operations. Flag any micro-optimisation committed as a
speedup without a wall-clock A/B over several runs with variance
reported. If the measured result was neutral, the finding is that it
must not be described as a speedup.

## 10. Build a tool when a correction recurs

If the same class of correction keeps being made by hand, the finding is
not the correction -- it is that nothing catches it. A check that cannot
be forgotten beats a habit that can.

Flag a diff that re-fixes something already fixed before without adding
the check that would have caught it.

Generic tools worth reusing across projects live in
`~/Documents/Projects/agent-config/scripts/`. Copy from there rather
than rewriting one that has already been built and tested; if more than
one looks relevant, check whether they duplicate a concept before
adopting both.

## 11. A correction replaces the claim it corrects

A deliverable states the current understanding. It does not narrate the
route there. Code, comments, reports, slides, notebooks -- all are read
by someone who never held the earlier belief, and spending their
attention on a retracted claim teaches them a wrong thing first and then
unteaches it.

```python
# Flag
# We previously computed this with a global fit, which explained only
# 9-38% of the variance. That conclusion was an artifact of the fit, not
# the model, so we now window it.
resid = windowed_residual(trace)

# Prefer: state why the current method is the right one
# Windowed because a shot's fringe phase drifts 1-2.7 fringes within one
# record, which no single global phase can absorb.
resid = windowed_residual(trace)
```

The previous conclusion belongs in the session chat, the commit message,
and the PR description -- all addressed to someone who was there. A
"Retraction" section in a report, or a retraction slide in a deck, is
the clearest form of the error: it is a whole unit of attention spent on
a claim the reader never had.

This binds the spec stage too, which is where it usually originates:
specify *replace claim X with Y*, never *add a retraction of X*. An
agent that writes a retraction slide is often following its brief
correctly.

Carve-out: a bug reproducer or a regression test legitimately records a
wrong past value, because the wrongness is the subject. Naming the
superseded value is then the point, not residue.

## 12. DRY forbids duplicated intent, not just duplicated lines

Two functions computing one quantity by different methods are a
violation even with no shared text. The tell is a comment asserting that
two implementations agree.

```python
# Flag: three routes to one least-squares fit, kept in step by hand
def fit_phase(theta, y): ...          # lstsq on [cos, sin, 1]
def windowed_residual(theta, y): ...  # same design matrix, per window
def measure_drift(theta, y):          # same fit, normal equations
    # Same (a, b) -> phase convention as fit_phase.
    ...

# Prefer: one solver, three callers
def fit_phase(theta, y, /, *, weights=None): ...
```

A comment that a convention must match across implementations is a
request for a human to do a compiler's job, and it is the thing that
silently breaks when one side changes.

Graded by layer. Strict in core library code. Relaxed in notebooks,
examples and one-off scripts, which are transient by design and whose
readability for a human experimenter outranks factoring -- see the
notebooks skill for that carve-out.

## Fallback lens: the classic smells

Weaker signals than the twelve rules above -- prefer a concrete rule
when one applies. All are judgement calls; distinguish a hard violation
from a matter of taste, and say which you are reporting. From Fowler,
*Refactoring*, ch. 3.

| Smell                                         | Definition                                                             | Usual remedy                                          |
| --------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------- |
| Mysterious Name                               | A name that does not reveal what the thing is for                      | Rename; if no good name exists, the design is wrong   |
| Duplicated Code                               | The same logic in more than one place                                  | Extract the shared form                               |
| Long Function                                 | A function doing several things at several levels of detail            | Extract until each does one thing                     |
| Long Parameter List                           | So many parameters the call site is unreadable                         | Bundle into a type, or pass the object that owns them |
| Global Data                                   | Mutable state anything can modify from anywhere                        | Encapsulate behind a narrow accessor                  |
| Mutable Data                                  | Data updated in place where callers do not expect it                   | Prefer values; confine mutation                       |
| Divergent Change                              | One module edited for several unrelated reasons                        | Split it by reason                                    |
| Shotgun Surgery                               | One conceptual change requiring edits scattered everywhere             | Consolidate into one place                            |
| Feature Envy                                  | A function using another object's data more than its own               | Move it next to the data                              |
| Data Clumps                                   | The same group of fields travelling together repeatedly                | Give the group a type                                 |
| Primitive Obsession                           | A primitive or string standing in for a domain concept                 | Introduce the domain type                             |
| Repeated Switches                             | The same switch or if-cascade recurring                                | Polymorphism, or one shared map                       |
| Loops                                         | A loop obscuring what is being computed                                | A named pipeline operation                            |
| Lazy Element                                  | A class or function too thin to justify existing                       | Inline it                                             |
| Speculative Generality                        | Abstraction added for a need nobody has stated                         | Delete it; inline until the need is real              |
| Temporary Field                               | A field only set some of the time                                      | Extract the object where it is always set             |
| Message Chains                                | Long navigation sequences like `a.b().c().d()`                         | Hide the chain behind one method                      |
| Middle Man                                    | A class or function that mostly just delegates                         | Call the target directly                              |
| Insider Trading                               | Modules reaching into each other's internals                           | Move the shared thing, or add a clear interface       |
| Large Class                                   | A class holding several unrelated responsibilities                     | Split by responsibility                               |
| Alternative Classes with Different Interfaces | Interchangeable classes that cannot be swapped                         | Unify the interface                                   |
| Data Class                                    | A class with fields and no behaviour, where behaviour exists elsewhere | Move the behaviour in (if it belongs)                 |
| Refused Bequest                               | A subclass ignoring most of what it inherits                           | Prefer composition                                    |
| Comments                                      | Comments used to excuse code that should be clearer                    | Fix the code; keep the why                            |
