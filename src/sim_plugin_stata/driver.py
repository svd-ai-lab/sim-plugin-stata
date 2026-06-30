"""Stata driver for sim.

Two execution paths, mirroring the MATLAB plugin:

- ``run_file`` runs a ``.do`` file one-shot through the Stata batch CLI
  (``StataMP-64.exe /e do file.do`` on Windows, ``stata-mp -b do file.do``
  on Unix). Stata batch mode writes its output to ``<stem>.log`` beside the
  do-file, so this driver runs the process and then reads that log back as
  the run's stdout.
- ``launch`` / ``run`` / ``disconnect`` drive a persistent in-process Stata
  session via **pystata**, the official Python API bundled with every Stata
  17+ install under ``<install>/utilities/pystata``. No pip dependency — the
  driver injects ``<install>/utilities`` onto ``sys.path`` and calls
  ``pystata.config.init(<edition>)``.

This module is SDK-free at import time: ``detect_installed`` and ``connect``
do NOT import ``pystata`` or launch Stata, so ``sim check stata`` works on a
host that has Stata installed but no session running.

There is deliberately **no GUI automation**. Stata is driven through its
batch CLI and pystata only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall
from sim.runner import detect_output_errors


# Stata prints fractional numbers with a leading dot and no zero (`.293`),
# which is not valid JSON. Insert a `0` before a `.` that directly follows a
# JSON structural char (`:`, `,`, `[`) or whitespace — never one that follows
# a digit or letter, so strings like "file.txt" are left untouched.
_LEADING_DOT_RE = re.compile(r"(?<=[:,\[\s])(-?)\.(\d)")


def _fix_stata_floats(line: str) -> str:
    return _LEADING_DOT_RE.sub(r"\g<1>0.\2", line)


# ─── editions ──────────────────────────────────────────────────────────────
#
# Stata ships several editions. The CLI binary name encodes which one. We
# rank them so that, when a single install dir carries more than one edition
# binary, detection prefers the most capable (MP > SE > BE > IC).
#
# pystata's ``config.init`` only accepts 'mp' / 'se' / 'be'. IC was renamed
# BE in Stata 17 (the first version to ship pystata), so a legacy 'ic' label
# maps to 'be' for session use.

_EDITION_RANK: dict[str, int] = {"mp": 4, "se": 3, "be": 2, "ic": 1}

# Map a binary stem (lower-cased, no extension) to an edition code.
_EDITION_FROM_STEM: dict[str, str] = {
    "statamp-64": "mp", "statamp": "mp", "stata-mp": "mp",
    "statase-64": "se", "statase": "se", "stata-se": "se",
    "statabe-64": "be", "statabe": "be", "stata-be": "be",
    "stataic-64": "ic", "stataic": "ic", "stata-ic": "ic",
    # The plain console binary on Unix (`stata`) is the BE edition.
    "stata-64": "be", "stata": "be",
}


def _session_edition(edition: str | None) -> str:
    """Coerce a detected edition label to one pystata accepts ('mp'/'se'/'be')."""
    ed = (edition or "mp").strip().lower()
    if ed == "ic":  # IC was renamed BE in Stata 17 (first pystata release).
        return "be"
    return ed if ed in {"mp", "se", "be"} else "mp"


# ─── version probes ─────────────────────────────────────────────────────────
#
# Same strategy-chain shape as the MATLAB / COMSOL drivers. Install-dir
# finders answer "where is Stata?"; version probes answer "which major
# version lives at <dir>?". Stata has no locale-invariant VersionInfo file
# the way MATLAB does, so the directory name is the primary signal.


def _version_from_dir_name(install_dir: Path) -> str | None:
    """Parse the Stata major version out of the install directory name.

    Catches the common layouts::

        C:\\Program Files\\Stata19\\          → 19
        C:\\Program Files\\StataNow19\\       → 19
        /usr/local/stata18/                   → 18
        /Applications/Stata/                  → (no version; returns None)
    """
    for part in (install_dir.name, install_dir.parent.name):
        m = re.search(r"stata(?:now)?[ _-]*(\d{2})\b", part, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


_VERSION_PROBES: list[Callable[[Path], str | None]] = [
    _version_from_dir_name,
]
"""Strategy chain. APPEND new probes for new Stata layouts; do not edit."""


def _read_install_version(install_dir: Path) -> str | None:
    for probe in _VERSION_PROBES:
        try:
            v = probe(install_dir)
        except Exception:
            v = None
        if v:
            return v
    return None


# ─── binary discovery ───────────────────────────────────────────────────────


def _stata_binaries(install_dir: Path) -> list[tuple[Path, str]]:
    """Return every Stata launcher binary present under ``install_dir``.

    Each item is ``(binary_path, edition_code)``. Covers Windows GUI exes,
    Unix console binaries, and the macOS ``.app`` bundle layout.
    """
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        if p in seen or not p.is_file():
            return
        ed = _EDITION_FROM_STEM.get(p.stem.lower())
        if ed is None:
            return
        seen.add(p)
        out.append((p, ed))

    # Windows GUI executables live directly in the install root.
    for stem in ("StataMP-64", "StataSE-64", "StataBE-64", "StataIC-64",
                 "StataMP", "StataSE", "StataBE", "StataIC"):
        add(install_dir / f"{stem}.exe")

    # Unix console binaries live in the install root.
    for name in ("stata-mp", "stata-se", "stata-be", "stata"):
        add(install_dir / name)

    # macOS .app bundles: <root>/StataMP.app/Contents/MacOS/{StataMP,stata-mp}.
    for app, ed_name in (("StataMP", "stata-mp"), ("StataSE", "stata-se"),
                         ("StataBE", "stata-be")):
        macos = install_dir / f"{app}.app" / "Contents" / "MacOS"
        add(macos / app)
        add(macos / ed_name)

    out.sort(key=lambda pe: _EDITION_RANK.get(pe[1], 0), reverse=True)
    return out


def _has_stata_binary(install_dir: Path) -> bool:
    return bool(_stata_binaries(install_dir))


def _make_install(install_dir: Path, source: str) -> SolverInstall | None:
    binaries = _stata_binaries(install_dir)
    if not binaries:
        return None
    primary_bin, primary_edition = binaries[0]
    version = _read_install_version(install_dir) or "?"
    editions = {ed: str(path) for path, ed in binaries}
    return SolverInstall(
        name="stata",
        version=version,
        path=str(install_dir),
        source=source,
        extra={
            "edition": primary_edition,
            "stata_exe": str(primary_bin),
            "editions": editions,
            "session_edition": _session_edition(primary_edition),
        },
    )


# ─── install-dir finders ────────────────────────────────────────────────────


def _candidates_from_env() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for var in ("STATA_ROOT", "STATAROOT", "STATA_HOME"):
        v = os.environ.get(var)
        if v and Path(v).is_dir():
            out.append((Path(v), f"env:{var}"))
    # STATABIN may point straight at the binary.
    b = os.environ.get("STATABIN")
    if b:
        bp = Path(b)
        if bp.is_file():
            out.append((bp.parent, "env:STATABIN"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for name in ("StataMP-64", "StataSE-64", "StataBE-64",
                 "stata-mp", "stata-se", "stata"):
        p = shutil.which(name)
        if p:
            out.append((Path(p).resolve().parent, f"which:{name}"))
    return out


def _candidates_from_windows_defaults() -> list[tuple[Path, str]]:
    """Probe ``C:\\Program Files\\Stata19\\`` and friends across drives.

    Soft name filter ("stata" substring) avoids walking every app under
    Program Files; the binary sniff in ``_make_install`` still gates
    emission, so non-Stata dirs are dropped.
    """
    bases: list[Path] = []
    for drive in ("C:", "D:", "E:", "F:"):
        bases.append(Path(rf"{drive}\Program Files"))
        bases.append(Path(rf"{drive}\Program Files (x86)"))
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for base in bases:
        if not base.is_dir():
            continue
        try:
            children = sorted(base.iterdir(), reverse=True)
        except OSError:
            continue
        for child in children:
            if "stata" not in child.name.lower():
                continue
            if not _has_stata_binary(child):
                continue
            rp = child.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append((child, f"default-path:{base}"))
    return out


def _candidates_from_unix_defaults() -> list[tuple[Path, str]]:
    """Probe common Linux/macOS install layouts."""
    bases = [
        Path("/usr/local"), Path("/opt"), Path("/usr/local/stata"),
        Path("/Applications"),
    ]
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for base in bases:
        if not base.is_dir():
            continue
        # Direct hit: the base itself is an install root.
        if _has_stata_binary(base):
            rp = base.resolve()
            if rp not in seen:
                seen.add(rp)
                out.append((base, f"default-path:{base}"))
        try:
            children = sorted(base.iterdir(), reverse=True)
        except OSError:
            continue
        for child in children:
            if "stata" not in child.name.lower():
                continue
            if not _has_stata_binary(child):
                continue
            rp = child.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append((child, f"default-path:{base}"))
    return out


_INSTALL_FINDERS: list[Callable[[], list[tuple[Path, str]]]] = [
    _candidates_from_env,
    _candidates_from_path,
    _candidates_from_windows_defaults,
    _candidates_from_unix_defaults,
]
"""Strategy chain. APPEND new finders for new Stata layouts; do not edit."""


def _scan_stata_installs() -> list[SolverInstall]:
    """Find every Stata installation on this host. Pure stdlib.

    Walks ``_INSTALL_FINDERS`` in order, dedupes by resolved install path,
    then reads each install's major version and edition set. Highest
    version first.
    """
    found: dict[str, SolverInstall] = {}
    for finder in _INSTALL_FINDERS:
        try:
            cands = finder()
        except Exception:
            continue
        for path, source in cands:
            inst = _make_install(path, source=source)
            if inst is None:
                continue
            key = str(Path(inst.path).resolve())
            found.setdefault(key, inst)
    return sorted(found.values(), key=lambda i: i.version, reverse=True)


# ─── safety guard ───────────────────────────────────────────────────────────
#
# Stata can shell out (`shell`, `!`, `winexec`) and delete files (`erase`,
# `rmdir`). An agent running arbitrary do-files should not do that silently.
# We scan submitted code for these and block by default; set
# SIM_STATA_ALLOW_SHELL=1 to bypass for a trusted workflow.

_DANGEROUS_CMDS = ("shell", "winexec", "erase", "rmdir", "unlink", "mkdir")
_DANGEROUS_RE = re.compile(
    r"^\s*(?:" + "|".join(_DANGEROUS_CMDS) + r")\b", re.IGNORECASE | re.MULTILINE
)
_SHELL_BANG_RE = re.compile(r"^\s*!", re.MULTILINE)


def _scan_dangerous(code: str) -> list[str]:
    """Return short snippets for each unsafe command found in ``code``.

    Skips line comments (``*`` / ``//``). Best-effort, line-oriented — a
    motivated user can still smuggle a shell-out, but this catches the
    accidental and the obvious.
    """
    if os.environ.get("SIM_STATA_ALLOW_SHELL", "").strip() in {"1", "true", "yes", "on"}:
        return []
    issues: list[str] = []
    for raw in code.splitlines():
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith("//"):
            continue
        if _DANGEROUS_RE.match(line) or _SHELL_BANG_RE.match(line):
            issues.append(line[:120])
    return issues


def _default_stata_probes() -> list:
    """Stata probe list — generic_probes() only.

    Stata is driven headless (batch CLI or pystata), so there are no GUI
    dialog / screenshot probes. Probes extract facts; "what counts as an
    error" is the agent's job, not the driver's.
    """
    from sim.inspect import generic_probes  # noqa: PLC0415

    return list(generic_probes())


class StataDriver:
    """Stata driver — one-shot batch execution and persistent pystata sessions.

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, run_file, detect_installed,
        plus launch / run / disconnect for sessions.
    """

    def __init__(self) -> None:
        self._pystata = None
        self._stata = None  # the `pystata.stata` submodule, once a session is live
        self._session_id: str | None = None
        self._edition: str | None = None
        self._version: str | None = None
        self._install_path: str | None = None
        self.probes: list = _default_stata_probes()
        self._sim_dir = Path.cwd() / ".sim"

    @property
    def name(self) -> str:
        return "stata"

    @property
    def supports_session(self) -> bool:
        return True

    # ── detection / availability ────────────────────────────────────────────

    def detect(self, script: Path) -> bool:
        """Treat ``.do`` (do-files) and ``.ado`` (ado programs) as Stata inputs."""
        return script.suffix.lower() in (".do", ".ado")

    def lint(self, script: Path) -> LintResult:
        """Lightweight static checks for a ``.do`` / ``.ado`` script.

        Stata has no first-party static linter, so this is intentionally
        shallow: confirm the file is a Stata script, that it reads, that
        braces balance, and surface any unsafe commands as warnings. Never
        raises — a missing file is a graceful ``ok=False`` result.
        """
        if script.suffix.lower() not in (".do", ".ado"):
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message="Not a Stata `.do` / `.ado` script",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError) as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"cannot read file: {e}")],
            )

        diagnostics: list[Diagnostic] = []
        if text.count("{") != text.count("}"):
            diagnostics.append(Diagnostic(
                level="warning",
                message=f"Unbalanced braces: {text.count('{')} '{{' vs "
                        f"{text.count('}')} '}}'",
            ))
        for snippet in _scan_dangerous(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message=f"Potentially unsafe command (blocked unless "
                        f"SIM_STATA_ALLOW_SHELL=1): {snippet}",
            ))
        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Report Stata availability via ``detect_installed`` (no launch)."""
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="stata",
                version=None,
                status="not_installed",
                message="No Stata installation detected on this host",
            )
        top = installs[0]
        edition = str(top.extra.get("edition", "?")).upper()
        return ConnectionInfo(
            solver="stata",
            version=top.version,
            status="ok",
            message=f"Stata {top.version} {edition} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Enumerate Stata installations visible on this host.

        Strategy chain (deduped by resolved install root):
          1. STATA_ROOT / STATABIN env vars
          2. PATH probe via `which StataMP-64` / `which stata-mp` / ...
          3. C:\\Program Files\\Stata<NN>\\Stata{MP,SE,BE}-64.exe (Windows)
          4. /usr/local/stata<NN>/, /Applications/Stata/ (Unix)

        Pure stdlib. Does NOT import pystata. Returns highest version first.
        Each install records its edition set in ``extra``.
        """
        return _scan_stata_installs()

    def parse_output(self, stdout: str) -> dict:
        """Parse the last JSON object printed by a Stata script / session.

        Same "last JSON line on stdout" convention as the MATLAB plugin.
        Stata batch output is read back from the ``.log`` file by
        ``run_file`` before being handed here.

        Tolerant of one Stata quirk: Stata prints fractional numbers with a
        leading dot and no zero (``.293`` instead of ``0.293``), which is not
        valid JSON. We try strict parse first, then retry with leading zeros
        inserted, so an agent emitting ``display`` values does not have to
        format every number defensively.
        """
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            for candidate in (line, _fix_stata_floats(line)):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        return {}

    # ── one-shot batch execution ────────────────────────────────────────────

    def _resolve_install(self, install_path: str | None = None) -> SolverInstall:
        if install_path:
            inst = _make_install(Path(install_path), source="explicit")
            if inst is not None:
                return inst
        installs = _scan_stata_installs()
        if installs:
            return installs[0]
        raise RuntimeError(
            "no Stata installation detected; set STATA_ROOT or pass install_path"
        )

    def _stata_specific_errors(self, log_text: str) -> list[str]:
        """Stata flags errors with a trailing ``r(<rc>);`` return code line."""
        errors: list[str] = []
        for m in re.finditer(r"^r\((\d+)\);", log_text, re.MULTILINE):
            errors.append(f"[stata] r({m.group(1)}); return code")
        return errors

    def run_file(self, script: Path) -> RunResult:
        """Execute a ``.do`` file one-shot through the Stata batch CLI.

        Windows : ``StataMP-64.exe /e do <file>``  → writes ``<stem>.log``
        Unix    : ``stata-mp -b do <file>``         → writes ``<stem>.log``

        The process is run with ``cwd = script.parent`` so the log lands
        beside the do-file and relative data paths inside the do-file
        resolve. Stata batch output goes to the log, not stdout, so we read
        the log back and use it as ``RunResult.stdout``.
        """
        install = self._resolve_install()
        exe = install.extra.get("stata_exe")
        if not exe:
            raise RuntimeError("resolved Stata install has no usable binary")

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise RuntimeError(f"cannot read do-file: {e}") from e

        blocked = _scan_dangerous(text)
        timestamp = datetime.now(timezone.utc).isoformat()
        if blocked:
            return RunResult(
                exit_code=126,
                stdout="",
                stderr="[sim-plugin-stata] blocked by safety guard; set "
                       "SIM_STATA_ALLOW_SHELL=1 to override:\n  " + "\n  ".join(blocked),
                duration_s=0.0,
                script=str(script),
                solver=self.name,
                timestamp=timestamp,
                errors=[f"blocked unsafe command: {s}" for s in blocked],
            )

        cwd = script.parent if str(script.parent) else Path.cwd()
        log_path = cwd / f"{script.stem}.log"
        try:
            if log_path.exists():
                log_path.unlink()
        except OSError:
            pass

        flag = "/e" if os.name == "nt" else "-b"
        cmd = [str(exe), flag, "do", script.name]

        start = time.monotonic()
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
        duration = time.monotonic() - start

        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace") \
                if log_path.is_file() else ""
        except OSError:
            log_text = ""
        stdout = (log_text or proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        errors = detect_output_errors(stdout, stderr)
        errors.extend(self._stata_specific_errors(stdout))
        exit_code = proc.returncode
        if exit_code == 0 and errors:
            exit_code = 1

        return RunResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=round(duration, 3),
            script=str(script),
            solver=self.name,
            timestamp=timestamp,
            errors=errors,
        )

    # ── persistent session via pystata ──────────────────────────────────────

    def launch(self, ui_mode: str = "no_gui", **kwargs) -> dict:
        """Start a persistent in-process Stata session via pystata.

        pystata ships with every Stata 17+ install; we add
        ``<install>/utilities`` to ``sys.path`` and call
        ``pystata.config.init(<edition>)``. pystata is headless only, so
        ``ui_mode`` is informational — there is no Stata GUI to attach.
        Optional kwargs: ``edition`` ('mp'/'se'/'be'), ``install_path``.
        """
        try:
            install = self._resolve_install(kwargs.get("install_path"))
        except RuntimeError as e:
            return {"ok": False, "error_code": "not_installed", "message": str(e)}

        edition = _session_edition(kwargs.get("edition") or install.extra.get("edition"))
        # pystata lives under <install>/utilities; the `sfi` module it needs at
        # init time lives under <install>/ado/base/py. pystata.config.init does
        # NOT add the latter when driven standalone, so we add both.
        for sub in ("utilities", os.path.join("ado", "base", "py")):
            p = Path(install.path) / sub
            if p.is_dir() and str(p) not in sys.path:
                sys.path.insert(0, str(p))

        try:
            import pystata  # noqa: PLC0415
            pystata.config.init(edition)
            # `stata` is a lazy submodule — it is NOT an attribute of the
            # top-level package until explicitly imported.
            from pystata import stata as stata_mod  # noqa: PLC0415
        except Exception as e:  # noqa: BLE001 — surface init failure to the agent
            return {
                "ok": False,
                "error_code": "session_launch_failed",
                "message": f"pystata init failed for edition {edition!r}: {e}",
            }

        self._pystata = pystata
        self._stata = stata_mod
        self._edition = edition
        self._version = install.version
        self._install_path = install.path
        self._session_id = str(uuid.uuid4())
        ui_note = None
        if ui_mode not in ("no_gui", "headless", ""):
            ui_note = (
                f"ui_mode={ui_mode!r} ignored — pystata sessions are headless; "
                "there is no Stata GUI to attach."
            )
        return {
            "ok": True,
            "session_id": self._session_id,
            "ui_mode": "no_gui",
            "edition": edition,
            "version": install.version,
            "ui_note": ui_note,
        }

    def _dispatch(self, code: str, label: str) -> dict:
        """Run Stata code in the live session, capturing output (no probes).

        pystata writes Stata output to the OS console fd, not Python's
        ``sys.stdout``, so ``redirect_stdout`` does not catch it. We use
        pystata's own ``config.set_output_file`` to tee the session output to
        a temp file and read it back — robust across pystata's streaming
        modes.
        """
        if self._stata is None:
            raise RuntimeError("No active Stata session.")
        self._sim_dir.mkdir(parents=True, exist_ok=True)
        cap = self._sim_dir / f"stata_out_{uuid.uuid4().hex[:8]}.txt"
        ok = True
        error = None
        try:
            self._pystata.config.set_output_file(str(cap), replace=True)
            try:
                self._stata.run(code, echo=False)
            finally:
                self._pystata.config.close_output_file()
        except Exception as e:  # noqa: BLE001 — Stata errors vary; surface as data
            ok = False
            error = str(e)
        try:
            stdout = cap.read_text(encoding="utf-8", errors="replace") \
                if cap.is_file() else ""
        except OSError:
            stdout = ""
        try:
            cap.unlink()
        except OSError:
            pass
        parsed = self.parse_output(stdout) if ok else None
        return {
            "ok": ok,
            "label": label,
            "stdout": stdout,
            "stderr": error or "",
            "error": error,
            "result": parsed,
        }

    def run(self, code: str, label: str = "snippet") -> dict:
        """Execute Stata code in the active session and attach diagnostics."""
        if self._pystata is None:
            return {
                "ok": False,
                "error_code": "no_session",
                "message": "No active Stata session; call launch() first.",
            }
        blocked = _scan_dangerous(code)
        if blocked:
            return {
                "ok": False,
                "error_code": "blocked_unsafe",
                "message": "blocked by safety guard (set SIM_STATA_ALLOW_SHELL=1 "
                           "to override): " + "; ".join(blocked),
            }

        from sim.inspect import InspectCtx, collect_diagnostics  # noqa: PLC0415

        wd = self._sim_dir
        try:
            wd.mkdir(parents=True, exist_ok=True)
            before = sorted(
                str(p.relative_to(wd)).replace("\\", "/")
                for p in wd.rglob("*") if p.is_file()
            )
        except Exception:
            before = []

        t0 = time.monotonic()
        result = self._dispatch(code, label)
        wall = time.monotonic() - t0
        result["duration_s"] = round(wall, 3)

        ctx = InspectCtx(
            stdout=result.get("stdout", "") or "",
            stderr=result.get("stderr", "") or result.get("error", "") or "",
            workdir=str(wd),
            wall_time_s=wall,
            exit_code=0 if result.get("ok") else 1,
            driver_name=self.name,
            session_ns={"_result": result.get("result")},
            workdir_before=before,
        )
        try:
            diags, arts = collect_diagnostics(self.probes, ctx)
            result["diagnostics"] = [d.to_dict() for d in diags]
            result["artifacts"] = [a.to_dict() for a in arts]
        except Exception:  # noqa: BLE001 — diagnostics are best-effort
            result.setdefault("diagnostics", [])
            result.setdefault("artifacts", [])
        return result

    def query(self, name: str) -> dict:
        """Named query against the live Stata session."""
        if name == "session.summary":
            return {
                "connected": self._pystata is not None,
                "session_id": self._session_id,
                "ui_mode": "no_gui",
                "edition": self._edition,
                "version": self._version,
            }
        if name == "data.summary":
            if self._pystata is None:
                return {"connected": False}
            try:
                from sfi import Data  # noqa: PLC0415
                return {
                    "connected": True,
                    "obs": int(Data.getObsTotal()),
                    "vars": int(Data.getVarCount()),
                    "varnames": list(Data.getVarName(i) for i in range(Data.getVarCount())),
                }
            except Exception as e:  # noqa: BLE001
                return {"connected": True, "error": str(e)}
        return {"error": f"unknown query: {name}"}

    def disconnect(self) -> dict:
        """Tear down the session handle. Idempotent.

        pystata runs in-process and has no clean per-session shutdown, so
        this drops our handle to it rather than killing a process. Calling
        on an already-disconnected driver is success, not an error.
        """
        sid = self._session_id
        self._pystata = None
        self._stata = None
        self._session_id = None
        self._edition = None
        self._version = None
        self._install_path = None
        return {"ok": True, "disconnected": True, "session_id": sid}
