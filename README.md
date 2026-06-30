# sim-plugin-stata

[Stata](https://www.stata.com) statistics/econometrics driver for
[sim-cli](https://github.com/svd-ai-lab/sim-cli), distributed as a plugin via
Python `entry_points`.

This plugin delegates to the local Stata batch CLI and to **pystata**,
StataCorp's official Python API that ships inside every Stata 17+ install. It
does **not** bundle Stata or any StataCorp SDK. See
[LICENSE-NOTICE.md](LICENSE-NOTICE.md).

**No GUI automation.** Stata is driven headless: one-shot `.do` files go
through the batch CLI, and persistent sessions go through pystata in-process.

## Install

For agent projects, install sim-cli-core and the Stata plugin in the project
environment:

```powershell
uv init  # only if this is not already a uv project
uv add sim-cli-core sim-plugin-stata
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check stata
uv run sim plugin doctor stata --deep
```

Persistent sessions need **no extra install**: pystata ships with Stata. The
driver puts `<install>/utilities` on `sys.path` and calls
`pystata.config.init(<edition>)` at launch. Sessions require Stata 17+ (the
first version to ship pystata); batch `.do` runs work on any Stata with a
batch CLI.

For Claude Code, sync the bundled skill to `.claude/skills` instead:

```powershell
uv run sim plugin sync-skills --target .claude/skills --copy
```

## How it works

The plugin registers via three entry-point groups:

```toml
[project.entry-points."sim.drivers"]
stata = "sim_plugin_stata:StataDriver"

[project.entry-points."sim.skills"]
stata = "sim_plugin_stata:skills_dir"

[project.entry-points."sim.plugins"]
stata = "sim_plugin_stata:plugin_info"
```

`sim.drivers` exposes the driver class, `sim.skills` exposes the bundled skill
files, and `sim.plugins` exposes catalogue-style metadata for local discovery.

`.do` files dispatch one-shot via `StataMP-64.exe /e do file.do` (Windows) or
`stata-mp -b do file.do` (Unix). Stata batch mode writes `<stem>.log` beside
the do-file, so the driver runs `cwd = <do-file's folder>` and reads the log
back as the run's stdout. End your do-file with a `display "{...}"` JSON line
and the driver's `parse_output()` picks it up.

Persistent sessions use pystata: `launch` → `pystata.config.init`, `run` →
`pystata.stata.run` (stdout captured), `disconnect` drops the handle.

A safety guard blocks `shell` / `!` / `winexec` / `erase` / `rmdir` / `unlink`
/ `mkdir` in submitted code unless `SIM_STATA_ALLOW_SHELL=1` is set.

## Develop

```bash
git clone https://github.com/svd-ai-lab/sim-plugin-stata
cd sim-plugin-stata
uv sync
uv run --extra test pytest -q        # unit tests run without Stata
```

To validate end-to-end against a local Stata, install this plugin into the
sim-cli environment and run:

```bash
uv run sim check stata
uv run sim run --solver stata fixtures/stata_ok.do
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [LICENSE-NOTICE.md](LICENSE-NOTICE.md).
