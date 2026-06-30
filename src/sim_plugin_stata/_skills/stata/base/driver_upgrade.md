---
name: driver-upgrade
description: Handle Stata driver/runtime upgrade work for sim, including CLI changes, pystata behavior across Stata versions, and edition/version detection adjustments.
---

# driver-upgrade Skill — Stata

Use this skill when:

- the `sim` Stata driver changes execution or query behavior
- Stata CLI behavior changes across versions (batch flags, log naming)
- pystata API compatibility needs verification on a new Stata release
- edition/version detection needs a new install layout added

Focus areas:

- compatibility risks (new Stata major version, renamed editions)
- behavioral regressions in batch `/e do` vs. `-b do`
- pystata `config.init` / `stata.run` / `sfi` deltas
- cross-driver contract alignment inside `sim` (RunResult, session return shapes)

Detection extension points live in `driver.py` as append-only strategy chains:
`_INSTALL_FINDERS` (where Stata lives) and `_VERSION_PROBES` (which version a
dir is). Add a new function; do not edit the validated existing ones.
