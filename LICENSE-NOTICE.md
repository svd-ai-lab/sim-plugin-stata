# License Notice

`sim-plugin-stata` is released under Apache-2.0 (see [LICENSE](LICENSE)).

## Vendor SDK / binary disclaimer

This plugin is a thin adapter that delegates to:

- **Stata** (the `StataMP-64.exe` / `stata-mp` binary and its batch CLI), a
  commercial product of StataCorp LLC.
- **`pystata`**, StataCorp's official Python API, which ships **inside** every
  Stata 17+ installation under `<install>/utilities/pystata`. It is loaded from
  the local Stata install at runtime — this project does not redistribute it.

This repository **does not bundle, redistribute, or otherwise embed** any
StataCorp binary, source, or SDK. Users are responsible for:

1. Obtaining a valid Stata license from StataCorp.
2. Installing Stata on the host where this plugin runs.
3. Using a Stata 17+ install if they want persistent pystata sessions (batch
   `.do` execution works on any Stata version with a batch CLI).

The Apache-2.0 license on this repository covers only the adapter code in
`src/sim_plugin_stata/`, which is original work.

Use of Stata itself is governed by the StataCorp license agreement, not by this
project's license.
