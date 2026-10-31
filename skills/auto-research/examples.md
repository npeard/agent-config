# Auto-research worked cases

Numbered as `SKILL.md` cites them. Open the one case you are acting on;
reading this end to end buys nothing.

### 1. The SMI interferogram amplitude

**What happened:** SMI project. This case comes from the user's account,
not a transcript. An interferogram fit gave poor goodness of fit. The
agent proposed fitting a time-varying envelope because the fringe rate
seemed to be changing. It was not: plotting the fit result against the
observed data showed the fitted amplitude was systematically too small.
The fit was stuck in a bad initial parameter regime; the model was
right.

**What to do:** before suggesting a different function, plot the fit
over the data and check the fitted parameters against first-principles
expectations. Here that comparison makes the too-small amplitude readily
apparent, and the problem is a bad starting regime, not a wrong model.

### 2. Over-reads in a synthetic research report

**What happened:** SMI project, from the fix lists of four independent
review rounds of an agent-written report. Each round caught the same two
shapes. Rankings: "What is resolved is that TCAN beats the TCN" rested
on one seed per cell and a 9% seed range measured at another budget, and
two roughly 10% leads were both called gains. Mechanisms: "Phase drift
masks most of the gain" was untested, since no subset ran with drift
removed; an offline model's failure was diagnosed with no run testing
the diagnosis.

**What to do:** compare each gap with the seed spread of its own
configuration, and call a gap inside it "at the edge of the seed range".
Write an untested cause as "one untested reading" and name the run that
would test it.
