# Snippets

Standalone Stata snippets used in step-by-step execution and debugging.

Guidance:

- keep snippets small and machine-verifiable
- end with a `display "{...}"` JSON line when they feed back into `sim`
  (the driver's `parse_output()` only reads the final `{`-prefixed line)
- separate exploratory snippets from stable workflow assets
- never include `shell` / `!` / `erase` — those are blocked by the safety guard

Minimal example (emits a parseable result line). Use Stata **compound double
quotes** `` `"..."' `` for literal `"` and interpolate numbers via macros — a
plain `""` inside `"..."` ends the string in Stata, it does not escape a quote:

```stata
sysuse auto, clear
quietly summarize price
local mean = r(mean)
local n = r(N)
display `"{"ok":true,"mean_price":`mean',"n":`n'}"'
```
