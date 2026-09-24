"""Remote guard behavior for reference files under the client home."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import (
    lint_session_cwd,
    lint_session_cwd_emit,
    lint_session_cwd_path_authority,
)
from yoke_core.hooks.types import HookContext, Outcome
from yoke_contracts.hook_runner.session_cwd import (
    CLIENT_MACHINE_HOME_KEY,
    CLIENT_MACHINE_HOME_SCHEMA,
    client_machine_home_fact,
)


SESSION_ID = "session-external-home"
ITEM_ID = 4817
SERVER_HOME = Path("/srv/yoke-server-home")
SECRET_TEXT = "fixture secret that must never be logged"


@pytest.fixture
def conn():
    with test_database() as connection:
        yield connection


@pytest.fixture
def client_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "client-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(SERVER_HOME))
    monkeypatch.setattr(
        lint_session_cwd_path_authority, "_STATIC_FREE_PATH_PREFIXES", (),
    )
    return home


@pytest.fixture
def claimed_worktree(conn, tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    worktree = repo / ".worktrees" / "external-home-test"
    worktree.mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", repo, 1)
    seed_item(conn, item_id=ITEM_ID, branch="external-home-test", repo_path=repo)
    seed_item_claim(conn, SESSION_ID, item_id=ITEM_ID)
    return worktree


def _remote_evaluation(
    tool_input: dict,
    *,
    client_home: Path,
    home_metadata: dict | None = None,
):
    payload = {
        "session_id": SESSION_ID,
        "tool_name": "Bash",
        "tool_input": tool_input,
    }
    if home_metadata is None:
        payload.update(client_machine_home_fact(str(client_home)))
    else:
        payload.update(home_metadata)
    return lint_session_cwd.evaluate(
        HookContext(
            event_name="PreToolUse",
            executor_family="codex",
            executor_surface="codex-cli",
            payload=payload,
            tool_name="Bash",
            session_id=SESSION_ID,
            remote=True,
        )
    )


def _cat(target: Path) -> dict[str, str]:
    return {"command": f"cat '{target}'"}


def test_relayed_bare_cat_allows_ordinary_client_home_reference(
    conn,
    claimed_worktree: Path,
    client_home: Path,
) -> None:
    reference = client_home / "Documents" / "reference.md"
    reference.parent.mkdir(parents=True)
    reference.write_text("ordinary reference\n")

    decision = _remote_evaluation(_cat(reference), client_home=client_home)

    assert decision.outcome is Outcome.NOOP, decision.message


@pytest.mark.parametrize("via_symlink", [False, True], ids=["direct", "symlink"])
def test_relayed_bare_cat_refuses_nested_dot_directory_targets(
    conn,
    claimed_worktree: Path,
    client_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    via_symlink: bool,
) -> None:
    private_file = client_home / "Documents" / ".private" / "token"
    private_file.parent.mkdir(parents=True)
    private_file.write_text(SECRET_TEXT)
    target = private_file
    if via_symlink:
        target = client_home / "Documents" / "reference.md"
        target.symlink_to(private_file)

    emitted = []
    monkeypatch.setattr(
        lint_session_cwd_emit,
        "_emit",
        lambda name, outcome, context, **_kwargs: emitted.append((name, context)),
    )
    decision = _remote_evaluation(_cat(target), client_home=client_home)

    assert decision.outcome is Outcome.DENY
    assert SECRET_TEXT not in decision.message
    assert emitted
    assert SECRET_TEXT not in str(emitted)


@pytest.mark.parametrize(
    "home_metadata",
    [
        pytest.param({}, id="missing"),
        pytest.param(
            {
                CLIENT_MACHINE_HOME_KEY: {
                    "schema": CLIENT_MACHINE_HOME_SCHEMA,
                    "root": "/clients/alice/../alice",
                }
            },
            id="invalid",
        ),
    ],
)
def test_relayed_bare_cat_fails_closed_without_valid_client_home_evidence(
    conn,
    claimed_worktree: Path,
    client_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    home_metadata: dict,
) -> None:
    reference = client_home / "Documents" / "reference.md"
    reference.parent.mkdir(parents=True)
    reference.write_text(SECRET_TEXT)
    emitted = []
    monkeypatch.setattr(
        lint_session_cwd_emit,
        "_emit",
        lambda name, outcome, context, **_kwargs: emitted.append((name, context)),
    )

    decision = _remote_evaluation(
        _cat(reference), client_home=client_home, home_metadata=home_metadata,
    )
    reason = json.loads(decision.message)["hookSpecificOutput"][
        "permissionDecisionReason"
    ]

    assert decision.outcome is Outcome.DENY
    assert "client machine-home metadata was missing or invalid" in reason
    assert "Restore the canonical client-home fact in the hook relay" in reason
    assert SECRET_TEXT not in reason
    assert emitted[0][1]["authority_reason"] == (
        lint_session_cwd.CLIENT_HOME_AUTHORITY_UNAVAILABLE
    )
    assert SECRET_TEXT not in str(emitted[0][1])
