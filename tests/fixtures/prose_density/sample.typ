// a comment with 99 numbers 1.5
#let values = json("v.json")
#let val(key) = values.at(key)

= Results <sec-results>

The error falls to 3.5% at 10 nm, and #val("gain") times below the baseline.

== Detail

The module `smi.theory` and smi.core.paths write plot_gain.py via run_baselines. See @fig-a.

$ E = m c^2 + 42 $

#fig(
  image("a.pdf"),
  caption: [Gain of 7.5 at 12 positions.],
) <fig-a>

#align(center, table(
  columns: 2,
  [a], [11], [b], [13],
)) <tab-a>

#figure(image("b.pdf"))

#table(
  columns: 3,
  table.header([x], [y], [z]),
  [p], [q], [r],
  [s], [t], [u],
) <tab-b>

#assert(val("ok"), message: "the 77 checks failed")

= Discussion

Prose states the claim with $x^2$ and no values.

```python
x = 123
```

#bibliography("refs.bib")
