"""Cursor's shell gate resolves to the Bash chain on every side of the relay.

``beforeShellExecution`` carries no ``tool_name``. The client must still pick
the Bash chain, collect every fact it reads, and hand the server a payload
whose watcher-capture paths lint-session-cwd can attribute to the session.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.cursor_tool_names import payload_tool_name
from yoke_contracts.hook_resident_routing import is_read_only_tool_event
from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_contracts.hook_runner.project_scope import HookProjectScope
from yoke_contracts.hook_runner.session_cwd import (
    CLIENT_MACHINE_HOME_KEY,
    CLIENT_SCRATCH_ROOT_KEY,
)
from yoke_contracts.machine_config.runtime import SCRATCH_ROOT_ENV
from yoke_core.domain import lint_session_cwd
from yoke_core.hooks.cursor_payload import parse_payload
from yoke_core.hooks.types import HookContext, Outcome
from yoke_harness.hooks import local_subset
from yoke_harness.hooks.client_facts import event_chain
from yoke_harness.hooks.deadline import HookDeadline


SESSION_ID = "cursor-session-owner"
CLIENT_ROOT = Path.home() / ".yoke" / "tmp"


@pytest.fixture
def conn():
    with test_database() as connection:
        yield connection


@pytest.fixture
def claimed_worktree(conn, tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    worktree = repo / ".worktrees" / "YOK-2100"
    worktree.mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", repo, 1)
    seed_item(conn, item_id=2100, branch="YOK-2100", repo_path=repo)
    seed_item_claim(conn, SESSION_ID, item_id=2100)
    return worktree


def _shell_gate(command: str, cwd: Path) -> dict:
    """The measured Cursor wire shape of a shell gate: no tool fields."""
    return {
        "hook_event_name": "beforeShellExecution",
        "session_id": SESSION_ID,
        "conversation_id": SESSION_ID,
        "command": command,
        "cwd": str(cwd),
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"hook_event_name": "beforeShellExecution", "command": "ls"}, "Bash"),
        ({"hook_event_name": "postToolUse", "tool_name": "Shell"}, "Bash"),
        ({"tool_name": "StrReplace"}, "Edit"),
        ({"tool_name": "Read"}, "Read"),
        ({"hook_event_name": "beforeSubmitPrompt"}, None),
    ],
)
def test_payload_tool_name_maps_cursor_shapes(payload: dict, expected) -> None:
    assert payload_tool_name(payload) == expected


def test_shell_gate_runs_the_bash_chain_on_client_and_resident(tmp_path: Path) -> None:
    raw = _shell_gate("ls", tmp_path)

    assert event_chain("PreToolUse", raw) == chain_for("PreToolUse", "Bash")
    assert is_read_only_tool_event("PreToolUse", json.dumps(raw)) is False
    assert parse_payload(json.dumps(raw))["tool_name"] == "Bash"


def test_shell_gate_collects_bash_facts_and_allows_watcher_capture(
    conn,
    claimed_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(SCRATCH_ROOT_ENV, str(CLIENT_ROOT))
    capture_dir = (
        CLIENT_ROOT
        / "1"
        / "sessions"
        / SESSION_ID
        / "runs"
        / "pid-444"
        / "watcher-captures"
    )
    raw_capture = capture_dir / "yoke-merge.raw.abc123.log"
    progress_capture = capture_dir / "yoke-merge.progress.abc123.log"
    command = (
        f"cd {claimed_worktree} && yoke --env prod watch merge "
        f"--raw-capture {raw_capture} --progress-capture {progress_capture} "
        "-- merge-item YOK-2100"
    )
    raw = json.dumps(_shell_gate(command, claimed_worktree))

    client = local_subset.evaluate_local_subset(
        "PreToolUse",
        raw,
        "cursor",
        None,
        HookDeadline(budget_ms=3000, started_at=time.monotonic()),
        collect_facts=True,
        project_scope=HookProjectScope(project_id=1),
    )

    assert client.denied is False
    assert client.payload_extra[CLIENT_SCRATCH_ROOT_KEY]["root"] == str(CLIENT_ROOT)
    assert client.payload_extra[CLIENT_MACHINE_HOME_KEY]["root"] == str(
        Path.home().resolve()
    )

    # The server folds the relayed facts into its own canonicalized payload.
    server_payload = {**parse_payload(raw), **client.payload_extra}
    monkeypatch.setenv(SCRATCH_ROOT_ENV, str(tmp_path / "server-scratch"))
    decision = lint_session_cwd.evaluate(
        HookContext(
            event_name="PreToolUse",
            executor_family="cursor",
            executor_surface="cursor",
            payload=server_payload,
            tool_name=server_payload["tool_name"],
            session_id=SESSION_ID,
            remote=True,
        )
    )
    assert decision.outcome is Outcome.NOOP, decision
