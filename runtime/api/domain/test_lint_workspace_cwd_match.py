"""Regression tests for ``lint_workspace_cwd_match``.

A session bound to a worktree may not run writer-class commands (pytest,
the renderer, the test runner) from a cross-checkout cwd; with no claim the
lint stays silent. Session and cwd come only from the payload. Static-scan
tests live in ``test_lint_workspace_repo_root_scan.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import lint_workspace_cwd_match
from yoke_core.domain.lint_workspace_cwd_match import (
    SUPPRESSION_TOKEN,
    evaluate_payload,
)
from yoke_core.hooks.types import HookContext, Outcome

SESSION = "fixture-session"


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
        "session_id": SESSION,
    }


def _claim_workspace(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
) -> None:
    """Claim *workspace* for the session the payload names, and only it."""
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match.resolve_session_worktree_paths",
        lambda session_id: [str(workspace)] if session_id == SESSION else [],
    )


def test_denies_event_622168_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bound to a worktree, running pytest from main is denied."""
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    _claim_workspace(monkeypatch, workspace)
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


def test_noop_without_worktree_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No active worktree claim means no check fires."""
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match.resolve_session_worktree_paths",
        lambda session_id: [],
    )
    payload = _event_622168_payload(str(tmp_path / "main"))
    assert evaluate_payload(payload) is None


# ---------------------------------------------------------------------------
# Cwd-under-workspace passes (no false positives for the happy path)
# ---------------------------------------------------------------------------


def test_pass_when_cwd_is_under_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    _claim_workspace(monkeypatch, workspace)
    payload = _event_622168_payload(str(workspace))
    assert evaluate_payload(payload) is None


def test_pass_when_cwd_is_a_subdirectory_of_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    sub = workspace / "runtime" / "api"
    sub.mkdir(parents=True)
    _claim_workspace(monkeypatch, workspace)
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
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    _claim_workspace(monkeypatch, workspace)
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match._read_mode",
        lambda payload=None: "deny",
    )
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(main_checkout),
        "session_id": SESSION,
    }
    verdict = evaluate_payload(payload)
    assert verdict is not None, f"expected denial for {command!r}"
    mode, _, _ = verdict
    assert mode == "deny"


def test_unrelated_commands_pass_through(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    _claim_workspace(monkeypatch, workspace)
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
            "session_id": SESSION,
        }
        assert evaluate_payload(payload) is None, (
            f"unexpected match for unrelated command: {command!r}"
        )


# ---------------------------------------------------------------------------
# Suppression-token audit shape
# ---------------------------------------------------------------------------


def test_suppression_token_records_audit_but_does_not_unblock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The suppression token is audit evidence only, never an unblock."""
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    _claim_workspace(monkeypatch, workspace)
    monkeypatch.setattr(
        "yoke_core.domain.lint_workspace_cwd_match._read_mode",
        lambda payload=None: "deny",
    )
    command = "python3 -m pytest runtime/harness/  " + SUPPRESSION_TOKEN
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(main_checkout),
        "session_id": SESSION,
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
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    _claim_workspace(monkeypatch, workspace)
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
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    _claim_workspace(monkeypatch, workspace)
    payload = {
        "tool_name": "Edit",
        "tool_input": {"command": "python3 -m pytest runtime/harness/"},
        "cwd": str(tmp_path / "main"),
        "session_id": SESSION,
    }
    assert evaluate_payload(payload) is None


# ---------------------------------------------------------------------------
# Session and cwd come from the payload, never the evaluating process
# ---------------------------------------------------------------------------


def _main_and_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "worktree"
    main_checkout = tmp_path / "main"
    workspace.mkdir()
    main_checkout.mkdir()
    _claim_workspace(monkeypatch, workspace)
    monkeypatch.setattr(
        lint_workspace_cwd_match, "_read_mode", lambda payload=None: "deny"
    )
    return main_checkout


def test_payload_without_session_allows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main_checkout = _main_and_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "yoke_core.domain.session_ambient_identity.resolve_ambient_session_id",
        lambda env=None: None,
    )
    payload = _event_622168_payload(str(main_checkout))
    payload.pop("session_id")
    assert evaluate_payload(payload) is None


def test_payload_without_cwd_allows_whatever_the_process_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main_checkout = _main_and_workspace(monkeypatch, tmp_path)
    monkeypatch.chdir(main_checkout)
    payload = _event_622168_payload(str(main_checkout))
    payload.pop("cwd")
    assert evaluate_payload(payload) is None


def test_verdict_is_the_same_locally_and_remotely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main_checkout = _main_and_workspace(monkeypatch, tmp_path)
    for cwd, outcome in (
        (str(main_checkout), Outcome.DENY),
        (str(tmp_path / "worktree" / "runtime"), Outcome.NOOP),
    ):
        payload = _event_622168_payload(cwd)
        decisions = [
            lint_workspace_cwd_match.evaluate(
                HookContext(
                    event_name="PreToolUse",
                    executor_family="claude",
                    executor_surface="claude",
                    payload=dict(payload),
                    remote=remote,
                )
            )
            for remote in (False, True)
        ]
        assert [d.outcome for d in decisions] == [outcome, outcome]
        assert decisions[0].message == decisions[1].message
