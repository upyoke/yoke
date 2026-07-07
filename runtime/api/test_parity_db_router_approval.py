"""Parity tests — shell vs Python approval domain parity."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import approval


_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPORT_MODULE = "yoke_core.tools.lifecycle_export"


def _shell_eval(export_type: str) -> str:
    """Run lifecycle_export and return its stdout (shell code)."""
    result = subprocess.run(
        [sys.executable, "-m", _EXPORT_MODULE, export_type],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, f"Export failed: {result.stderr}"
    return result.stdout


def _shell_var(shell_code: str, var_name: str) -> str:
    """Extract a shell variable value by eval-ing the code in sh."""
    script = f'{shell_code}\necho "${var_name}"'
    result = subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Shell eval failed: {result.stderr}"
    return result.stdout.strip()


def _shell_fn_check(shell_code: str, fn_name: str, arg: str) -> bool:
    """Invoke a shell function from the generated code, return True if exit 0."""
    script = f'{shell_code}\n{fn_name} "{arg}"'
    result = subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


class TestApprovalParity_ShellPython:
    """AC-2: Verify shell adapter exports match Python domain approval values."""

    @pytest.fixture(scope="class")
    def shell_code(self):
        return _shell_eval("approval")

    def test_halt_states_match(self, shell_code):
        """APPROVAL_HALT_STATES in shell == HaltState enum values in Python."""
        shell_val = set(_shell_var(shell_code, "APPROVAL_HALT_STATES").split())
        python_val = set(h.value for h in approval.HaltState)
        assert shell_val == python_val

    def test_actions_match(self, shell_code):
        """APPROVAL_ACTIONS in shell == ApprovalAction enum values in Python."""
        shell_val = set(_shell_var(shell_code, "APPROVAL_ACTIONS").split())
        python_val = set(a.value for a in approval.ApprovalAction)
        assert shell_val == python_val

    def test_stage_authority_field_matches(self, shell_code):
        """STAGE_AUTHORITY_FIELD matches Python constant."""
        assert _shell_var(shell_code, "STAGE_AUTHORITY_FIELD") == approval.STAGE_AUTHORITY_FIELD

    def test_stage_cache_field_matches(self, shell_code):
        """STAGE_CACHE_FIELD matches Python constant."""
        assert _shell_var(shell_code, "STAGE_CACHE_FIELD") == approval.STAGE_CACHE_FIELD

    def test_scope_matches(self, shell_code):
        """APPROVAL_SCOPE matches Python constant."""
        assert _shell_var(shell_code, "APPROVAL_SCOPE") == approval.APPROVAL_SCOPE

    def test_is_halt_state_parity(self, shell_code):
        """is_halt_state behaves identically in shell and Python."""
        for state in [h.value for h in approval.HaltState]:
            py_result = approval.is_halt_state(state)
            sh_result = _shell_fn_check(shell_code, "is_halt_state", state)
            assert py_result == sh_result, f"Mismatch for '{state}'"

        for bad in ("bogus", "approved", "pending"):
            py_result = approval.is_halt_state(bad)
            sh_result = _shell_fn_check(shell_code, "is_halt_state", bad)
            assert py_result == sh_result, f"Mismatch for invalid '{bad}'"

    def test_is_approval_action_parity(self, shell_code):
        """is_approval_action behaves identically in shell and Python."""
        for action in [a.value for a in approval.ApprovalAction]:
            py_result = approval.is_approval_action(action)
            sh_result = _shell_fn_check(shell_code, "is_approval_action", action)
            assert py_result == sh_result, f"Mismatch for '{action}'"

        for bad in ("bogus", "reject", "deny"):
            py_result = approval.is_approval_action(bad)
            sh_result = _shell_fn_check(shell_code, "is_approval_action", bad)
            assert py_result == sh_result, f"Mismatch for invalid '{bad}'"
