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
