"""Protocol-conformance test — plugged into sim-cli's shared harness."""
from __future__ import annotations

from sim.testing import assert_protocol_conformance
from sim_plugin_stata import StataDriver


def test_protocol_conformance() -> None:
    """Drives every conformance check sim-cli requires of a plugin driver."""
    assert_protocol_conformance(StataDriver)


def test_lint_missing_file_returns_diagnostic(tmp_path) -> None:
    """Missing / non-Stata paths should be lint failures, not IO errors."""
    result = StataDriver().lint(tmp_path / "missing.tmp")

    assert result.ok is False
    assert result.diagnostics
    assert result.diagnostics[0].level == "error"
