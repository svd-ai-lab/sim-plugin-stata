---
name: stata-sim
description: Use when running Stata `.do` files, checking a local Stata install, or driving Stata through the simplest real headless path. Choose direct Stata batch CLI or pystata when available, and use sim-cli's Stata plugin when standardized execution, persistent sessions, diagnostics, JSON extraction, safety guards, and artifact handling are useful. There is no GUI automation; Stata is driven headless through its batch CLI and pystata only.
---

# stata-sim

You are working with **Stata**. This skill is self-contained for Stata-specific
work: direct local availability probing, one-shot batch runs, local persistent
pystata sessions, version/edition probing, the log-based output convention, the
shell-out safety guard, and acceptance/escalation points.

Before requiring sim-cli, verify the intended Stata control path from direct
local evidence: a user-provided path, Stata batch executables on `PATH`, common
Stata install roots, or a visible `<install>/utilities/pystata` package for the
installed edition. Missing sim-cli is not evidence that Stata is missing. When
sim-cli is already selected/available or the task needs run history,
standardized validation, persistent sessions, JSON extraction, safety guards,
or plugin diagnostics, run:

```bash
uv run sim check stata
```

For direct one-shot execution, Stata's batch CLI is a valid smoke path when it
is visible in the current runtime. For one-shot execution through sim-cli, use
`uv run sim run --solver stata <file.do>`. For a local persistent session
through sim-cli, use `uv run sim connect --solver stata`, then bounded
`uv run sim exec` snippets, then `uv run sim disconnect`.

**No GUI.** This plugin never automates the Stata GUI. Batch runs go through
the Stata batch CLI; sessions go through **pystata**, Stata's official
in-process Python API. Do not ask for, or rely on, clicking the Stata
interface.

## Execution model

| Path | Mechanism | Output |
|---|---|---|
| One-shot `.do` | `StataMP-64.exe /e do file.do` (Win) / `stata-mp -b do file.do` (Unix) | Stata writes `<stem>.log` beside the do-file; the driver reads it back as `stdout` |
| Persistent session | `pystata.config.init(<edition>)` + `pystata.stata.run(code)` | stdout captured in-process; parsed for the final JSON line |

pystata ships **inside** every Stata 17+ install at
`<install>/utilities/pystata`. The driver puts `<install>/utilities` on
`sys.path` at launch — there is nothing to `pip install`. See
[`compatibility.yaml`](../../compatibility.yaml).

**Before opening a session, check the active Python version.** pystata loads
Stata's `stata_plugin` C bridge into the *running* interpreter, so a session
only works on a Python version StataCorp built that Stata release for
(Stata 19 → CPython ≤ 3.13 as of 2026; newer Stata releases extend the range).
Detect it up front — run `python --version` (or `uv run python --version`) and
confirm it is within the range the installed Stata supports before
`uv run sim connect`. If a session fails at init with
`No module named 'stata_plugin'`, the active Python is too new: run sim from a
supported interpreter, or fall back to one-shot batch `uv run sim run` (which
shells out to the Stata binary and is **version-independent**). See
[`base/reference/stata_driver.md`](base/reference/stata_driver.md#python-version-constraint-for-sessions).

## Stata-specific hard constraints

These add to — do not replace — the shared skill's hard constraints.

1. **Stata output is not structured by default.** End each task by emitting an
   explicit JSON line that the driver's `parse_output()` picks up. The parser
   reads the **last** line that starts with `{`. Build JSON with Stata's
   **compound double quotes** `` `"..."' `` so literal `"` survive, and
   interpolate numbers through local macros:

   ```stata
   quietly summarize price
   local mean = r(mean)
   local n = r(N)
   display `"{"ok":true,"mean":`mean',"n":`n'}"'
   ```

   Two Stata quirks the parser handles for you, but worth knowing:
   - A plain `""` inside a `"..."` string is **not** an escaped quote — it
     ends the string. Use compound quotes `` `"..."' `` (above) for literal
     `"`; the `""` doubling trick from MATLAB does not work here.
   - Stata prints fractions with a leading dot (`.293`, not `0.293`), which is
     invalid JSON. `parse_output()` repairs leading-dot numbers automatically,
     so you do not have to format every value defensively.

   Free-form `display`/`list` output is fine for humans but gets ignored by
   the parser unless it is that final `{...}` line.

2. **Batch output lives in the `.log`, not stdout.** `run_file` runs Stata with
   `cwd = <do-file's folder>` so `<stem>.log` and relative data paths resolve
   there. If you need the raw Stata session text, read the returned `stdout`
   (which IS the log) or the `<stem>.log` file.

3. **The safety guard blocks shell-outs by default.** `shell`, a leading `!`,
   `winexec`, `erase`, `rmdir`, `unlink`, and `mkdir` are blocked in both
   `run_file` and session `run`. To run a do-file that legitimately needs one,
   set `SIM_STATA_ALLOW_SHELL=1` for that invocation — never as a blanket
   default. See [`base/reference/safety.md`](base/reference/safety.md).

4. **Errors surface as `r(<rc>);`.** Stata stops a batch run at the first error
   and writes a `r(198);`-style return code to the log. The driver scans for
   these and marks the run failed even if the process exit code is 0. When you
   see `r(<n>);`, look at the line above it — that is the command that failed.

5. **Don't depend on workspace survival across one-shot runs.** Each
   `uv run sim run` is its own Stata process. Chain `uv run sim run` calls for
   pipelines, or use a persistent session if you need data to persist in memory.

## Layered content

Always read `base/`, then your active `sdk/<version>/`.

### `base/` — always relevant

| Path | What's there |
|---|---|
| `base/reference/stata_driver.md` | Batch vs. session contract, the log/JSON convention, edition & version probing, `r(rc)` handling. |
| `base/reference/safety.md` | The shell-out guard: what's blocked, why, and how to override deliberately. |
| `base/reference/README.md` | Index of Stata-specific reference notes (econometrics patterns land here as discovered). |
| `base/snippets/` | Ready-made `uv run sim run` / `uv run sim exec` payloads for common analyses. |
| `base/workflows/` | End-to-end multi-step examples. |
| `base/driver_upgrade.md` | Process notes for bumping Stata version / pystata behavior. |

### `sdk/<version>/` — version specifics

Per-Stata-version deltas. Empty stubs by default; notes land here as discovered.

- `sdk/19/notes.md` — Stata 19 / StataNow 19
- `sdk/18/notes.md` — Stata 18

### Documentation lookup

The authoritative route for any Stata command question is **Stata's own
`help` / `search`**, from a live session:

```bash
uv run sim exec "help regress"
uv run sim exec "help reghdfe"      # community-contributed, if installed
uv run sim exec "search difference in differences"
```

This reflects the commands and user-written packages actually installed (via
`ssc install`), respects your Stata version, and needs no internet. For longer
prose, Stata's PDF manuals ship with the install; the online reference is at
`https://www.stata.com/help.cgi` and `https://www.stata.com/manuals/`.

## Required protocol (one paragraph)

Follow the shared skill's required protocol for the **one-shot batch** model.
Stata-specific steps: confirm the `.do` file exists and its data dependencies
are reachable from the do-file's folder (that is the run's cwd); confirm the
final line emits a structured `{...}` JSON object via `display`; run
`uv run sim run --solver stata <file.do>`; read the returned `stdout` (the
log), let `parse_output()` pick up the JSON line, scan for any `r(<rc>);`, and
evaluate against the user's acceptance criterion per the shared skill's
`acceptance.md`. For multi-step pipelines, chain `uv run sim run` calls (each
is its own Stata process) or open one persistent session with
`uv run sim connect` and issue bounded `uv run sim exec` snippets.
