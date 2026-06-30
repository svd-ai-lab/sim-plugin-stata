"""Tests for the Stata driver."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sim_plugin_stata import StataDriver
from sim_plugin_stata import driver as drv

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fake_install_dir(tmp_path: Path, name: str = "Stata19",
                      exe: str = "StataMP-64.exe") -> tuple[Path, Path]:
    d = tmp_path / name
    d.mkdir()
    binary = d / exe
    binary.write_text("")
    return d, binary


class TestStataDetect:
    def test_detects_do_script(self):
        assert StataDriver().detect(FIXTURES / "stata_ok.do") is True

    def test_detects_ado_script(self, tmp_path):
        ado = tmp_path / "myprog.ado"
        ado.write_text("program define myprog\nend\n")
        assert StataDriver().detect(ado) is True

    def test_rejects_python_script(self, tmp_path):
        py = tmp_path / "x.py"
        py.write_text("print(1)\n")
        assert StataDriver().detect(py) is False


class TestStataParseOutput:
    def test_parses_last_json_line(self):
        driver = StataDriver()
        log = '. display "{...}"\n{"status":"ok","obs":74}\n'
        payload = driver.parse_output(log)
        assert payload["status"] == "ok"
        assert payload["obs"] == 74

    def test_empty_returns_empty_dict(self):
        assert StataDriver().parse_output("") == {}

    def test_tolerates_stata_leading_dot_floats(self):
        # Stata prints fractions as `.293`, which is invalid JSON; the parser
        # repairs it to `0.293` on retry.
        out = StataDriver().parse_output('{"ok":true,"r2":.293,"n":74}')
        assert out == {"ok": True, "r2": 0.293, "n": 74}

    def test_tolerates_negative_leading_dot_float(self):
        assert StataDriver().parse_output('{"x":-.5}') == {"x": -0.5}

    def test_does_not_corrupt_dotted_string(self):
        # A `.` inside a string value must not be touched.
        assert StataDriver().parse_output('{"f":"a.b"}') == {"f": "a.b"}


class TestVersionEditionProbing:
    def test_version_from_dir_name(self, tmp_path):
        d, _ = _fake_install_dir(tmp_path, "StataNow19")
        assert drv._version_from_dir_name(d) == "19"

    def test_make_install_reads_edition_and_version(self, tmp_path):
        d, exe = _fake_install_dir(tmp_path, "Stata18", "StataSE-64.exe")
        inst = drv._make_install(d, source="test:synth")
        assert inst is not None
        assert inst.version == "18"
        assert inst.extra["edition"] == "se"
        assert inst.extra["stata_exe"] == str(exe)

    def test_make_install_prefers_mp_over_se(self, tmp_path):
        d = tmp_path / "Stata19"
        d.mkdir()
        (d / "StataSE-64.exe").write_text("")
        (d / "StataMP-64.exe").write_text("")
        inst = drv._make_install(d, source="test:synth")
        assert inst is not None
        assert inst.extra["edition"] == "mp"

    def test_make_install_none_without_binary(self, tmp_path):
        d = tmp_path / "Stata19"
        d.mkdir()
        assert drv._make_install(d, source="test:synth") is None


class TestSessionEdition:
    def test_ic_maps_to_be(self):
        assert drv._session_edition("ic") == "be"

    def test_unknown_defaults_mp(self):
        assert drv._session_edition("zzz") == "mp"

    def test_passthrough(self):
        assert drv._session_edition("SE") == "se"


class TestStataConnect:
    def test_reports_not_installed_when_missing(self, monkeypatch):
        monkeypatch.setattr(drv, "_INSTALL_FINDERS", [lambda: []])
        info = StataDriver().connect()
        assert info.status == "not_installed"

    def test_reports_ok_with_synthetic_install(self, monkeypatch, tmp_path):
        d, _ = _fake_install_dir(tmp_path, "Stata19")
        monkeypatch.setattr(drv, "_INSTALL_FINDERS",
                            [lambda: [(d, "test:synth")]])
        info = StataDriver().connect()
        assert info.status == "ok"
        assert info.version == "19"
        assert "MP" in info.message


class TestSafetyGuard:
    def test_blocks_shell(self):
        issues = drv._scan_dangerous("sysuse auto\nshell rm -rf /\n")
        assert issues and "shell" in issues[0]

    def test_blocks_bang(self):
        assert drv._scan_dangerous("! del important.dta")

    def test_allows_clean_code(self):
        assert drv._scan_dangerous("sysuse auto, clear\nsummarize price") == []

    def test_skips_comments(self):
        assert drv._scan_dangerous("* shell rm -rf /\n// erase x.dta") == []

    def test_override_env(self, monkeypatch):
        monkeypatch.setenv("SIM_STATA_ALLOW_SHELL", "1")
        assert drv._scan_dangerous("shell echo hi") == []

    def test_run_file_blocks_unsafe(self, monkeypatch, tmp_path):
        # subprocess must NOT be invoked when the guard trips.
        def boom(*a, **k):
            raise AssertionError("subprocess.run should not be called")
        monkeypatch.setattr(drv.subprocess, "run", boom)
        d, _ = _fake_install_dir(tmp_path, "Stata19")
        monkeypatch.setattr(drv, "_INSTALL_FINDERS",
                            [lambda: [(d, "test:synth")]])
        script = tmp_path / "bad.do"
        script.write_text("sysuse auto\nshell rm -rf /\n")
        result = StataDriver().run_file(script)
        assert result.exit_code == 126
        assert result.errors


class TestStataRunFile:
    def test_batch_command_and_log_readback(self, monkeypatch, tmp_path):
        d, exe = _fake_install_dir(tmp_path, "Stata19")
        monkeypatch.setattr(drv, "_INSTALL_FINDERS",
                            [lambda: [(d, "test:synth")]])

        script = tmp_path / "run.do"
        script.write_text('display "{""ok"":true}"\n')

        recorded = {}

        def fake_run(command, cwd, capture_output, text):
            recorded["command"] = command
            recorded["cwd"] = cwd
            # Stata writes <stem>.log in cwd; simulate that.
            (Path(cwd) / "run.log").write_text(
                '. display "{""ok"":true}"\n{"ok":true}\n'
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(drv.subprocess, "run", fake_run)

        result = StataDriver().run_file(script)
        assert result.exit_code == 0
        assert recorded["command"][0] == str(exe)
        # /e on Windows, -b elsewhere — both followed by `do <name>`.
        assert recorded["command"][1] in ("/e", "-b")
        assert recorded["command"][2] == "do"
        assert recorded["command"][3] == "run.do"
        assert result.stdout.strip().endswith('{"ok":true}')
        assert StataDriver().parse_output(result.stdout) == {"ok": True}

    def test_r_return_code_marks_failure(self, monkeypatch, tmp_path):
        d, _ = _fake_install_dir(tmp_path, "Stata19")
        monkeypatch.setattr(drv, "_INSTALL_FINDERS",
                            [lambda: [(d, "test:synth")]])
        script = tmp_path / "err.do"
        script.write_text("regress nonexistent\n")

        def fake_run(command, cwd, capture_output, text):
            (Path(cwd) / "err.log").write_text(
                "variable nonexistent not found\nr(111);\n"
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(drv.subprocess, "run", fake_run)
        result = StataDriver().run_file(script)
        # Exit code 0 from process, but r(111); in the log -> marked failed.
        assert result.exit_code != 0
        assert any("r(111)" in e for e in result.errors)


class TestStataLint:
    def test_rejects_non_stata(self, tmp_path):
        result = StataDriver().lint(tmp_path / "x.py")
        assert result.ok is False
        assert result.diagnostics[0].level == "error"

    def test_warns_unbalanced_braces(self, tmp_path):
        do = tmp_path / "x.do"
        do.write_text("program define p\n  display 1\n")  # missing closing brace? braces count
        do.write_text("foreach x in a b {\n  display `x'\n")  # unbalanced {
        result = StataDriver().lint(do)
        assert result.ok is True  # warnings only
        assert any("brace" in d.message.lower() for d in result.diagnostics)

    def test_warns_unsafe_command(self, tmp_path):
        do = tmp_path / "x.do"
        do.write_text("sysuse auto\nshell echo hi\n")
        result = StataDriver().lint(do)
        assert any("unsafe" in d.message.lower() for d in result.diagnostics)


class TestSessionWithoutStata:
    def test_run_without_session_returns_error(self):
        out = StataDriver().run("display 1")
        assert out["ok"] is False
        assert out["error_code"] == "no_session"

    def test_disconnect_is_idempotent(self):
        driver = StataDriver()
        first = driver.disconnect()
        second = driver.disconnect()
        assert first["ok"] is True and first["disconnected"] is True
        assert second["ok"] is True and second["disconnected"] is True
