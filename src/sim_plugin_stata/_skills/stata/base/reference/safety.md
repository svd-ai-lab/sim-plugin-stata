# Stata shell-out safety guard

Stata can run arbitrary operating-system commands and delete files. An agent
executing user- or model-authored do-files should not do that silently, so the
driver scans submitted code and **blocks these by default**:

| Pattern | Why it's blocked |
|---|---|
| `shell <cmd>` | runs an arbitrary OS command |
| `! <cmd>` (leading bang) | shorthand for `shell` |
| `winexec <cmd>` | launches a Windows program |
| `erase`, `unlink` | deletes files |
| `rmdir` | removes directories |
| `mkdir` | creates directories (filesystem mutation) |

The scan is line-oriented and skips `*` / `//` comments. It runs in both
`run_file` (one-shot) and session `run`.

## Overriding deliberately

When a do-file legitimately needs one of these (e.g. calling an external
estimator, or `mkdir` for an output folder), set the environment variable for
that invocation only:

```powershell
$env:SIM_STATA_ALLOW_SHELL = '1'
uv run sim run --solver stata pipeline_with_shell.do
Remove-Item Env:\SIM_STATA_ALLOW_SHELL
```

Never set it as a blanket default in a shared environment. Prefer rewriting the
do-file to avoid the shell-out (use Stata's native `copy`, `filefilter`,
`mkdir` alternatives, or do the OS step outside Stata where the agent can see
it) over disabling the guard.

## What the guard does NOT do

It is a guardrail, not a sandbox. It is line-oriented and can be bypassed by a
motivated author (macro indirection, `cap noi`, etc.). It exists to stop the
accidental and the obvious. For untrusted do-files, run them in a throwaway
working directory and review the `.do` source first — `uv run sim lint
<file.do>` surfaces the same unsafe-command warnings without executing.
