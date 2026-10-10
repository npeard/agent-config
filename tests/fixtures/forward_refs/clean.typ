= Setup <sec:setup>
See @sec:setup, @fig:later, @tab:later and @elsewhere.
Details are in @app:proof and @eq:in-float.
// A commented-out forward pointer: @sec:result
$ x = 1 $ <eq:first>
#figure(
  rect(),
  caption: [A float],
) <fig:later>
#figure(
  table(columns: 1, [a]),
  caption: [A table],
) <tab:later>
#figure(
  rect(),
  caption: [Labelled without a prefix],
) <eq:in-float>
= Appendix
== Proof <app:proof>
This reuses @sec:setup and @eq:first.
