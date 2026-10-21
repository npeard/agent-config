# Notebook worked cases

Numbered as the rules in `SKILL.md` cite them. Open the one case you are
acting on; reading this end to end buys nothing.

### 1. A helper wrapping a fit, called once

From the user's account of helper functions and wrappers in cells, not a
transcript. The pair below is illustrative of that account.

**Before:**

```python
def fit_decay(t, y):
    return curve_fit(lambda t, a, tau: a * np.exp(-t / tau), t, y)

popt, _ = fit_decay(t, y)
```

**After:**

```python
AMPLITUDE_GUESS = 1.0  # arb.
TAU_GUESS = 5.0  # us

popt, _ = curve_fit(
    lambda t, a, tau: a * np.exp(-t / tau), t, y, p0=[AMPLITUDE_GUESS, TAU_GUESS]
)
```
