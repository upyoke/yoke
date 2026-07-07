"""Regression tests for ``lint_workspace_cwd_match``.

Covers the FR-9 acceptance criteria:

- ``test_denies_event_622168_shape``: the exact pytest-from-main
  shape that leaked state across checkouts is denied when
  ``$YOKE_BOUND_WORKSPACE`` points at a worktree and cwd is main.
- ``test_noop_when_workspace_unset``: the lint allows the same
  command when ``$YOKE_BOUND_WORKSPACE`` is unset (operator/maintenance
  mode flexibility preserved).
- Supporting tests round out the writer-verb allowlist, the cwd-under-
  workspace pass case, the suppression-token audit shape, and the warn
  mode fallthrough.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.lint_workspace_cwd_match import (
    BOUND_WORKSPACE_ENV_VAR,
    SUPPRESSION_TOKEN,
    evaluate_payload,
)


# ---------------------------------------------------------------------------
# Event-622168 replay
# ---------------------------------------------------------------------------


def _event_622168_payload(cwd: str) -> dict:
    """Construct the exact event-622168 Bash payload shape."""
    return {
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "_tmp=$(mktemp /tmp/yoke-pytest-main.XXXXXX); "
                "python3 -m pytest runtime/harness/ -q --no-header 2>&1 | tail -5; "
                'rm -f "$_tmp"'
            ),
        },
        "cwd": cwd,
        "session_id": "fixture-session",
    }


def test_denies_event_622168_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """AC-7: bound to a worktree, running pytest from main is denied."""
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    # Mock the machine-config read to a stub that says deny:
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match._read_mode",
        lambda payload=None: "deny",
    )
    payload = _event_622168_payload(str(main_checkout))
    verdict = evaluate_payload(payload)
    assert verdict is not None, "expected denial verdict for event-622168 shape"
    mode, reason, outcome = verdict
    assert mode == "deny"
    assert outcome == "denied"
    assert "writer-class command" in reason
    assert str(workspace) in reason
    assert str(main_checkout) in reason


def test_noop_when_workspace_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """AC-8: env var unset means no check fires."""
    monkeypatch.delenv(BOUND_WORKSPACE_ENV_VAR, raising=False)
    payload = _event_622168_payload(str(tmp_path / "main"))
    assert evaluate_payload(payload) is None


# ---------------------------------------------------------------------------
# Cwd-under-workspace passes (no false positives for the happy path)
# ---------------------------------------------------------------------------


def test_pass_when_cwd_is_under_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    payload = _event_622168_payload(str(workspace))
    assert evaluate_payload(payload) is None


def test_pass_when_cwd_is_a_subdirectory_of_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    sub = workspace / "runtime" / "api"
    sub.mkdir(parents=True)
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    payload = _event_622168_payload(str(sub))
    assert evaluate_payload(payload) is None


# ---------------------------------------------------------------------------
# Writer-verb allowlist coverage (renderer CLI, run_tests, bare pytest)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pytest runtime/harness/",
        "python3 -m pytest runtime/harness/",
        "env PYTHONPATH=/repo python3 -m pytest runtime/harness/",
        "env -u PYTHONPATH python3 -m pytest runtime/harness/",
        "python3 -m yoke_core.domain.agents_render render",
        "env YOKE_RENDER_TARGET_ROOT=/repo python3 -m yoke_core.domain.agents_render render",
        "python3 -m yoke_core.tools.run_tests --suite quick",
    ],
)
def test_writer_verb_allowlist_denies_each_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str,
) -> None:
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match._read_mode",
        lambda payload=None: "deny",
    )
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(main_checkout),
    }
    verdict = evaluate_payload(payload)
    assert verdict is not None, f"expected denial for {command!r}"
    mode, _, _ = verdict
    assert mode == "deny"


def test_unrelated_commands_pass_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    # Non-writer Bash shapes — should not match the lint at all.
    for command in (
        "git status",
        "grep -r foo /tmp",
        "ls -la",
        "echo hello",
        "python3 -m yoke_core.cli.db_router items get 1 status",
    ):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(main_checkout),
        }
        assert evaluate_payload(payload) is None, (
            f"unexpected match for unrelated command: {command!r}"
        )


# ---------------------------------------------------------------------------
# Suppression-token audit shape
# ---------------------------------------------------------------------------


def test_suppression_token_records_audit_but_does_not_unblock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """AC-17: the suppression token is audit evidence only, never an unblock."""
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match._read_mode",
        lambda payload=None: "deny",
    )
    command = (
        "python3 -m pytest runtime/harness/  " + SUPPRESSION_TOKEN
    )
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(main_checkout),
    }
    verdict = evaluate_payload(payload)
    assert verdict is not None
    mode, _, outcome = verdict
    assert mode == "deny", "suppression token must NOT unblock the rule"
    assert outcome == "suppression_attempted"


# ---------------------------------------------------------------------------
# Warn mode fallthrough
# ---------------------------------------------------------------------------


def test_warn_mode_audits_without_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match._read_mode",
        lambda payload=None: "warn",
    )
    payload = _event_622168_payload(str(main_checkout))
    verdict = evaluate_payload(payload)
    assert verdict is not None
    mode, reason, _ = verdict
    assert mode == "warn"
    assert "[mode=warn]" in reason


# ---------------------------------------------------------------------------
# Tool filter — non-Bash payloads ignored
# ---------------------------------------------------------------------------


def test_non_bash_tool_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    monkeypatch.setenv(BOUND_WORKSPACE_ENV_VAR, str(workspace))
    payload = {
        "tool_name": "Edit",
        "tool_input": {"command": "python3 -m pytest runtime/harness/"},
        "cwd": str(tmp_path / "main"),
    }
    assert evaluate_payload(payload) is None


# AC-6 / AC-7 static-scan tests live in
# ``test_lint_workspace_repo_root_scan.py`` so this file stays under the
# 350-line authoring cap. That sibling module exercises the helper at
# ``lint_workspace_repo_root_scan.scan_repo_root_references``.
