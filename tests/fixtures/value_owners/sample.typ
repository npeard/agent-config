#let val(key) = key

= Results

Nominal RMSE is #val("rmse_nominal") and #val("only_prose") here, see @tab-a.
The table repeats #val("prose_and_table") at the nominal point.

#table(
  columns: 2,
  [RMSE], [#val("rmse_nominal")],
  [Other], [#val("prose_and_table")],
) <tab-a>

#figure(
  image("b.pdf"),
  caption: [Nominal RMSE of #val("rmse_nominal").],
) <fig-b>

#figure(
  image("c.pdf"),
  caption: [Twice: #val("repeat_key") and #val("repeat_key").],
) <fig-c>

#figure(
  image("d.pdf"),
  caption: [Anonymous #val("anon_key").],
)

#figure(
  image("e.pdf"),
  caption: [Anonymous again #val("anon_key").],
)
