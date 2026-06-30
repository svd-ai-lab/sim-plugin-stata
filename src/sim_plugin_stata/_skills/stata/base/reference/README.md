# Reference

Stata-specific runtime notes, curated patterns, and lightweight task templates
for the `sim` Stata driver.

Current content:

- [`stata_driver.md`](stata_driver.md) — batch vs. session execution contract,
  the log/JSON output convention, edition & version probing, `r(rc)` handling.
- [`safety.md`](safety.md) — the shell-out safety guard and how to override it
  deliberately.

Planned content (lands here as discovered):

- econometrics patterns: OLS / IV (`ivregress`) / panel (`xtreg`) / fixed
  effects (`reghdfe`) / GMM, each with a JSON-emitting result line
- causal designs: DiD, event study, RDD (`rdrobust`), synthetic control
- data hygiene: reproducible `use`/`save`, `frames`, missing-data handling
- community packages worth `ssc install` (reghdfe, coefplot, estout, gtools)
