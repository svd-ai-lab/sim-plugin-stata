# Workflows

End-to-end Stata workflows an agent can execute through `sim`.

Planned examples:

- load → clean → regress → export a structured JSON summary (one-shot `.do`)
- a script that writes a results table / figure plus a JSON pointer to it
- a persistent-session workflow: `uv run sim connect --solver stata`, a few
  bounded `uv run sim exec` snippets that build up an in-memory dataset, then
  `uv run sim disconnect`
- a multi-step pipeline chained across several `uv run sim run` calls (each its
  own Stata process, results passed via saved `.dta` files)
