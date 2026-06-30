# Stata 19 / StataNow 19 notes

Latest tested combo. The patterns in `base/` work unchanged on this version.

- Batch: `StataMP-64.exe /e do file.do` (Windows) writes `file.log` in cwd.
- pystata ships at `<install>/utilities/pystata`; `config.init('mp'|'se'|'be')`.
- Validated live on Windows (StataMP-64, 16-core MP) for both a batch `/e do`
  run and a persistent pystata session.

This file exists so the layer is non-empty and the skills layout check passes.
