# Changelog

## 0.1.0 - 2026-06-30

- Initial release. Stata driver for sim-cli, distributed as an out-of-tree
  plugin via `entry_points`, modelled on `sim-plugin-matlab`.
- One-shot batch execution: `.do` files run through the Stata batch CLI
  (`StataMP-64.exe /e do file.do` on Windows, `stata-mp -b do file.do` on
  Unix). Stata writes `<stem>.log` beside the do-file; the driver reads it
  back as `RunResult.stdout` and scans it for generic errors plus Stata
  `r(<rc>);` return codes.
- Persistent sessions via **pystata** (StataCorp's official Python API,
  bundled inside every Stata 17+ install). `launch` puts
  `<install>/utilities` on `sys.path` and calls `pystata.config.init(<edition>)`;
  `run` executes via `pystata.stata.run` with stdout captured; `disconnect`
  is idempotent. No PyPI dependency for sessions.
- Detection (`detect_installed`) is SDK-free: env vars (`STATA_ROOT` /
  `STATABIN`), `PATH`, Windows `Program Files\Stata<NN>\`, and Unix
  `/usr/local/stata<NN>/` / `/Applications/Stata/`. Edition (MP/SE/BE/IC) is
  read from the binary name; major version from the install directory name.
- Safety guard: `shell`, leading `!`, `winexec`, `erase`, `rmdir`, `unlink`,
  and `mkdir` are blocked in both batch and session execution unless
  `SIM_STATA_ALLOW_SHELL=1` is set. Surfaced as `sim lint` warnings too.
- **No GUI automation** — Stata is driven headless through its batch CLI and
  pystata only.
- Bundled `stata-sim` skill: routing `SKILL.md`, `base/reference/`
  (driver contract + safety), snippets/workflows stubs, and `sdk/{19,18}` notes.
