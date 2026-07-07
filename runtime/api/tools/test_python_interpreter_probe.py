"""Tests for ``yoke_core.tools.python_interpreter_probe``.

Covers the typed-result shape, the fail-open contract on every uncertain
state (no python3, exec failure, timeout, non-sentinel stderr), the
confirmed-failure path that produces an advisory, and the
``YOKE_PYTHON`` override.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_core.tools import python_interpreter_probe as probe_mod
from yoke_core.tools.python_interpreter_probe import (
    OVERRIDE_ENV_VAR,
    SENTINEL_MODULE,
    SUBPROCESS_TIMEOUT_S,
    ProbeResult,
    probe,
    render_advisory,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(OVERRIDE_ENV_VAR, raising=False)


def _stub_subprocess(monkeypatch, *, returncode: int, stderr: str = ""):
    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=returncode, stderr=stderr, stdout="")
    monkeypatch.setattr(probe_mod.subprocess, "run", _fake_run)


class TestProbeHappyPath:
    def test_returns_ok_when_sentinel_imports_cleanly(self, monkeypatch):
        monkeypatch.setattr(
            probe_mod.shutil, "which",
            lambda name: "/opt/homebrew/bin/python3",
        )
        _stub_subprocess(monkeypatch, returncode=0)
        result = probe()
        assert result == ProbeResult(
            ok=True,
            resolved_python="/opt/homebrew/bin/python3",
            missing_module=None,
            override_used=False,
        )


class TestProbeFailOpen:
    def test_no_python3_on_path_is_fail_open(self, monkeypatch):
        monkeypatch.setattr(probe_mod.shutil, "which", lambda _name: None)
        result = probe()
        assert result.ok is True
        assert result.resolved_python is None
        assert result.missing_module is None

    def test_exec_failure_is_fail_open(self, monkeypatch):
        monkeypatch.setattr(
            probe_mod.shutil, "which",
            lambda name: "/some/python3",
        )

        def _raise_oserror(*_args, **_kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(probe_mod.subprocess, "run", _raise_oserror)
        result = probe()
        assert result.ok is True
        assert result.missing_module is None

    def test_timeout_is_fail_open(self, monkeypatch):
        monkeypatch.setattr(
            probe_mod.shutil, "which",
            lambda name: "/some/python3",
        )

        def _raise_timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="x", timeout=SUBPROCESS_TIMEOUT_S)

        monkeypatch.setattr(probe_mod.subprocess, "run", _raise_timeout)
        result = probe()
        assert result.ok is True
        assert result.missing_module is None

    def test_unexpected_stderr_is_fail_open(self, monkeypatch):
        # Non-zero exit with stderr that does NOT match the sentinel
        # signature: probe must fail open, not fire the advisory.
        monkeypatch.setattr(
            probe_mod.shutil, "which",
            lambda name: "/some/python3",
        )
        _stub_subprocess(
            monkeypatch, returncode=1,
            stderr="SyntaxError: unexpected token",
        )
        result = probe()
        assert result.ok is True
        assert result.missing_module is None


class TestProbeConfirmedFailure:
    def test_apple_python_missing_pydantic_fires_advisory(self, monkeypatch):
        monkeypatch.setattr(
            probe_mod.shutil, "which",
            lambda name: "/usr/bin/python3",
        )
        _stub_subprocess(
            monkeypatch, returncode=1,
            stderr="ModuleNotFoundError: No module named 'pydantic'\n",
        )
        result = probe()
        assert result.ok is False
        assert result.resolved_python == "/usr/bin/python3"
        assert result.missing_module == SENTINEL_MODULE
        assert result.override_used is False


class TestYokePythonOverride:
    def test_override_skips_path_lookup(self, monkeypatch):
        monkeypatch.setenv(OVERRIDE_ENV_VAR, "/custom/python3")
        # If which is called the test fails — override must win.
        monkeypatch.setattr(
            probe_mod.shutil, "which",
            lambda _name: pytest.fail("shutil.which should not be called"),
        )
        _stub_subprocess(monkeypatch, returncode=0)
        result = probe()
        assert result.resolved_python == "/custom/python3"
        assert result.override_used is True
        assert result.ok is True

    def test_override_failure_notes_override_in_advisory(self, monkeypatch):
        monkeypatch.setenv(OVERRIDE_ENV_VAR, "/bad/python3")
        _stub_subprocess(
            monkeypatch, returncode=1,
            stderr="ModuleNotFoundError: No module named 'pydantic'\n",
        )
        result = probe()
        assert result.override_used is True
        rendered = render_advisory(result)
        assert OVERRIDE_ENV_VAR in rendered
        assert "/bad/python3" in rendered
        assert "already set" in rendered


class TestRenderAdvisory:
    def test_empty_for_ok_result(self):
        ok = ProbeResult(
            ok=True, resolved_python="/x", missing_module=None,
            override_used=False,
        )
        assert render_advisory(ok) == ""

    def test_advisory_names_canonical_homebrew_and_override(self):
        bad = ProbeResult(
            ok=False, resolved_python="/usr/bin/python3",
            missing_module=SENTINEL_MODULE, override_used=False,
        )
        rendered = render_advisory(bad)
        assert "pydantic" in rendered
        assert "/usr/bin/python3" in rendered
        assert OVERRIDE_ENV_VAR in rendered
        # One of the canonical Homebrew paths must appear.
        assert (
            "/opt/homebrew/bin/python3" in rendered
            or "/usr/local/bin/python3" in rendered
        )


class TestSentinelImportableHere:
    """The test process must itself have the sentinel — otherwise the
    whole Yoke backend test suite would not be importable. This is a
    cheap meta-assertion that catches accidental sentinel renames."""

    def test_sentinel_imports_in_current_interpreter(self):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {SENTINEL_MODULE}"],
            capture_output=True, text=True, timeout=5,
        )
        assert proc.returncode == 0, proc.stderr


