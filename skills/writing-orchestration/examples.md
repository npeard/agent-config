# Writing-orchestration worked cases

Numbered as the rules in `SKILL.md` cite them. Open the one case you are
acting on; reading this end to end buys nothing.

### 10. Figure 2 and Figure 3 estimators

**What happened:** from the user's account, not a transcript. Figure 2
moved to a new estimator that it had shared with Figure 3, and the
caption of Figure 3 was edited to say it uses a different one.

**What to do:** regenerate Figure 3 with the same estimator, or lead
with the reason it differs.

### 11. Two reports in one directory

**What happened:** the multi-report test. Five scaffolded reports at
depths 1-3 sharing one `--shared` directory built. `proposal.typ` failed
`report-check`; a shared bibliography raised Snakemake
`MissingInputException`; an `#image` into another report's `build/` was
"file not found" when that report was unbuilt.

**What to do:** follow the four conventions in `SKILL.md`: separate
Snakefiles, shared scripts and data but never another report's `build/`.
