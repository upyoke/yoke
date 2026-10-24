"""Shell forms the ripgrep and path-glob guards must pass, beside the forms they still deny."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import lint_unmatched_path_glob as lint
from yoke_harness.hooks.local_policy_common import DENY
from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob


def _denied(command: str, cwd: Path) -> tuple[bool, bool]:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command, "shell": "/bin/zsh"},
        "cwd": str(cwd),
        "session_id": "sess-test",
    }
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        core = lint.evaluate_payload(payload) is not None
    return core, lint_unmatched_path_glob(payload).outcome == DENY


def _lint_tree(root: Path) -> Path:
    (root / "lib").mkdir()
    (root / "lib" / "lint_a.py").write_text("", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "command",
    [
        "rg -o -U 'name: (\\w+)' -r '$1' docs",
        "rg -o PAT --replace '$1' docs",
        "rg -or'$1' PAT docs",
    ],
)
def test_ripgrep_capture_replacement_passes(tmp_path: Path, command: str) -> None:
    assert _denied(command, tmp_path) == (False, False)


@pytest.mark.parametrize("command", ["rg -rn PAT docs", "rg -r PAT docs", "rg -nr x PAT docs"])
def test_ripgrep_recursive_misuse_is_still_denied(tmp_path: Path, command: str) -> None:
    assert _denied(command, tmp_path) == (True, True)


@pytest.mark.parametrize(
    "command",
    [
        "L=(lib/lint_*.py lib/other.py); print -l $L",
        "L=(lib/other.py lib/lint_*.py)",
        "L=(lib/lint_*.py)",
        "L+=(lib/lint_*.py)",
    ],
)
def test_array_assignment_with_matching_glob_passes(tmp_path: Path, command: str) -> None:
    assert _denied(command, _lint_tree(tmp_path)) == (False, False)


@pytest.mark.parametrize("command", ["L=(lib/missing_*.py)", "L=(lib/x.py lib/missing_*.py)"])
def test_array_assignment_with_unmatched_glob_is_still_denied(
    tmp_path: Path, command: str
) -> None:
    assert _denied(command, _lint_tree(tmp_path)) == (True, True)
