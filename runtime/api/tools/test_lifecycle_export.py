"""Tests for ``lifecycle_export.py``.

These tests cover the surviving ``approval`` export, which is still
runtime-sourced by ``approval-vocabulary.sh``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

from yoke_core.domain.approval import HaltState
from yoke_core.tools.lifecycle_export import generate_approval
from runtime.api.test_service_client import _REPO_ROOT, _with_source_pythonpath


# ---------------------------------------------------------------------------
# Approval export tests
# ---------------------------------------------------------------------------

APPROVAL_EXPECTED_VARS = [
    "APPROVAL_SCOPE",
    "APPROVAL_HALT_STATES",
    "APPROVAL_ACTIONS",
    "STAGE_AUTHORITY_FIELD",
    "STAGE_CACHE_FIELD",
]

APPROVAL_EXPECTED_FUNCTIONS = [
    "is_halt_state",
    "is_approval_action",
]


class TestApprovalExport:
    """Tests for the approval shell export."""

    def test_contains_all_expected_variables(self) -> None:
        output = generate_approval()
        for var in APPROVAL_EXPECTED_VARS:
            assert f'{var}="' in output, f"Missing variable: {var}"

    def test_contains_all_expected_functions(self) -> None:
        output = generate_approval()
        for func in APPROVAL_EXPECTED_FUNCTIONS:
            assert f"{func}()" in output, f"Missing function: {func}"

    def test_valid_posix_shell(self) -> None:
        output = generate_approval()
        result = subprocess.run(
            ["sh", "-n"],
            input=output,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Shell syntax error: {result.stderr}"

    def test_is_halt_state_matches_python(self) -> None:
        """Generated is_halt_state must agree with Python for all members + invalid."""
        from yoke_core.domain.approval import is_halt_state

        output = generate_approval()
        # Test all valid halt states
        for hs in HaltState:
            script = textwrap.dedent(f"""\
                eval '{_escape_for_eval(output)}'
                is_halt_state "{hs.value}"
            """)
            rc = _run_shell(script)
            assert rc == 0, f"is_halt_state({hs.value!r}) should return 0"
            assert is_halt_state(hs.value) is True

        # Test invalid halt states
        for invalid in ["bogus", "not-a-halt"]:
            script = textwrap.dedent(f"""\
                eval '{_escape_for_eval(output)}'
                is_halt_state "{invalid}"
            """)
            rc = _run_shell(script)
            assert rc != 0, f"is_halt_state({invalid!r}) should return non-zero"
            assert is_halt_state(invalid) is False


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCLI:
    """Tests for the CLI entry point."""

    _LIFECYCLE_MODULE = "yoke_core.tools.lifecycle_export"

    def _run_lifecycle_export(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", self._LIFECYCLE_MODULE, *args],
            capture_output=True,
            text=True,
            env=_with_source_pythonpath(),
            cwd=_REPO_ROOT,
        )

    def test_approval_subcommand_exits_zero(self) -> None:
        result = self._run_lifecycle_export("approval")
        assert result.returncode == 0

    def test_lifecycle_subcommand_exits_nonzero(self) -> None:
        # The CLI rejects unknown subcommands with a clean usage error.
        result = self._run_lifecycle_export("lifecycle")
        assert result.returncode != 0

    def test_invalid_subcommand_exits_nonzero(self) -> None:
        result = self._run_lifecycle_export("bogus")
        assert result.returncode != 0

    def test_no_args_exits_nonzero(self) -> None:
        result = self._run_lifecycle_export()
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape_for_eval(shell_code: str) -> str:
    """Escape single quotes for embedding in a single-quoted eval string."""
    return shell_code.replace("'", "'\"'\"'")


def _run_shell(script: str) -> int:
    """Run a shell script and return the exit code."""
    result = subprocess.run(
        ["sh", "-e"],
        input=script,
        capture_output=True,
        text=True,
    )
    return result.returncode
