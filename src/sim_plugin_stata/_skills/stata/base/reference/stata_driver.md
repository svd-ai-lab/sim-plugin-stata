# Stata driver — execution contract

How `sim-plugin-stata` runs Stata. No GUI is ever automated.

## One-shot batch (`run_file`)

`uv run sim run --solver stata file.do` dispatches to:

- **Windows:** `StataMP-64.exe /e do file.do`
- **Unix:** `stata-mp -b do file.do`

Both run the do-file in batch and exit, writing a log named `<stem>.log` in
the current working directory. The driver:

1. Resolves the Stata binary from `detect_installed()` (highest version,
   most capable edition: MP > SE > BE).
2. Runs the process with `cwd = file.do`'s parent, so `<stem>.log` lands
   beside the do-file and relative data/`use`/`save` paths resolve there.
3. Reads `<stem>.log` back and returns it as `RunResult.stdout`.
4. Scans the log for generic error patterns **and** Stata's `r(<rc>);`
   return-code lines; if any are found the run is marked failed even when
   the OS exit code is 0.

The do-file's own log is overwritten on each run (stale logs are removed
first).

## The JSON-on-log output convention

Stata produces unstructured text. To hand a structured result back to the
agent, make the **last** `{`-prefixed line of the log a JSON object, built
with Stata's **compound double quotes** `` `"..."' `` and macro interpolation:

```stata
sysuse auto, clear
quietly regress price mpg weight
local r2 = e(r2)
local n = e(N)
display `"{"ok":true,"r2":`r2',"n":`n'}"'
```

`parse_output()` walks the log bottom-up and returns the first line that
parses as JSON. Two Stata-specific gotchas it accounts for:

- **Quoting:** a plain `""` inside `"..."` is *not* an escaped quote in Stata —
  it terminates the string (so `display "{""ok""}"` prints `{ok}`, not
  `{"ok"}`). Use compound double quotes `` `"..."' `` for literal `"`.
- **Leading-dot floats:** Stata prints `.293`, not `0.293`. That is invalid
  JSON, so `parse_output()` retries with leading zeros inserted (`.293` →
  `0.293`) when a strict parse fails.

## Persistent session (pystata)

`launch()` adds `<install>/utilities` to `sys.path`, imports `pystata`, and
calls `pystata.config.init(<edition>)` where edition is `mp` / `se` / `be`.
`run(code)` calls `pystata.stata.run(code, echo=False)` with stdout redirected
into a buffer, then parses the final JSON line. pystata is in-process and
headless; `disconnect()` drops the handle (there is no separate Stata process
to kill).

`query("session.summary")` returns connection/edition/version. `query(
"data.summary")` uses the `sfi` (Stata Function Interface) `Data` class to
report obs/var counts and variable names from the in-memory dataset. The
driver also adds `<install>/ado/base/py` to `sys.path` at launch, because the
`sfi` module pystata needs lives there (not under `utilities/`).

### Python-version constraint for sessions

pystata loads Stata's `stata_plugin` C bridge **into the running Python
interpreter**, so the interpreter must be a version StataCorp built that
release for. Stata 19 supports CPython up to ~3.13 (as of 2026). Launching a
session under a newer Python (e.g. 3.14) fails at init with
`No module named 'stata_plugin'`. If you need persistent sessions, run sim
from a Python ≤3.13 environment.

**Batch `.do` runs are unaffected** — `run_file` shells out to the Stata
binary, so it works on any Python version. When the session path is
unavailable, fall back to one-shot `uv run sim run --solver stata <file.do>`
calls.

## Edition & version probing

`detect_installed()` is pure stdlib — it never imports pystata or launches
Stata. It finds installs via env vars (`STATA_ROOT`, `STATABIN`), `PATH`,
Windows `Program Files\Stata<NN>\`, and Unix `/usr/local/stata<NN>/` /
`/Applications/Stata/`. The binary stem encodes the edition
(`StataMP-64` → mp, `StataSE-64` → se, …); the major version is read from the
install directory name (`Stata19` / `StataNow19` → `19`). When a dir name
carries no version, the install is still reported with `version="?"`.
