"""Relayed session-cwd authority uses the command machine's home."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd
from yoke_core.hooks.types import HookContext, Outcome
from yoke_contracts.hook_runner.session_cwd import (
    CLIENT_MACHINE_HOME_KEY,
    CLIENT_MACHINE_HOME_SCHEMA,
    client_machine_home,
    client_machine_home_fact,
)


SESSION_ID = "session-machine-home"
ITEM_ID = 2197
CLIENT_HOME = Path("/clients/alice")
SERVER_HOME = Path("/srv/yoke-server-home")
ICLOUD_DOCUMENT = CLIENT_HOME / (
    "Library/Mobile Documents/com~apple~CloudDocs/Docs/Yoke/icon/build/animate_yoke.py"
)


@pytest.fixture
def conn():
    with test_database() as connection:
        yield connection


@pytest.fixture(autouse=True)
def _writable_server_scratch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scratch = tmp_path / "server-scratch"
    scratch.mkdir()
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(scratch))


@pytest.fixture
def recorded_worktree(conn, tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    worktree = repo / ".worktrees" / "YOK-2197"
    worktree.mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", repo, 1)
    seed_item(conn, item_id=ITEM_ID, branch="YOK-2197", repo_path=repo)
    return worktree


@pytest.fixture
def claimed_worktree(conn, recorded_worktree: Path) -> Path:
    seed_item_claim(conn, SESSION_ID, item_id=ITEM_ID)
    return recorded_worktree


def _remote_evaluation(
    tool_name: str,
    tool_input: dict,
    *,
    include_home: bool = True,
):
    payload = {
        "session_id": SESSION_ID,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if include_home:
        payload.update(client_machine_home_fact(str(CLIENT_HOME)))
    return lint_session_cwd.evaluate(
        HookContext(
            event_name="PreToolUse",
            executor_family="codex",
            executor_surface="codex-cli",
            payload=payload,
            tool_name=tool_name,
            session_id=SESSION_ID,
            remote=True,
        )
    )


def _remote_decision(tool_name: str, tool_input: dict, **kwargs) -> Outcome:
    return _remote_evaluation(tool_name, tool_input, **kwargs).outcome


@pytest.mark.parametrize(
    "root",
    ["relative/home", "/", "/clients/alice/../alice"],
)
def test_client_home_contract_rejects_noncanonical_or_broad_roots(root: str) -> None:
    assert (
        client_machine_home(
            {
                CLIENT_MACHINE_HOME_KEY: {
                    "schema": CLIENT_MACHINE_HOME_SCHEMA,
                    "root": root,
                }
            }
        )
        == ""
    )


def test_client_home_contract_accepts_a_canonical_scoped_root() -> None:
    fact = client_machine_home_fact(str(CLIENT_HOME))
    assert fact == {
        CLIENT_MACHINE_HOME_KEY: {
            "schema": CLIENT_MACHINE_HOME_SCHEMA,
            "root": str(CLIENT_HOME),
        }
    }
    assert client_machine_home(fact) == str(CLIENT_HOME)


def test_external_reference_read_survives_claim_acquisition(
    conn,
    recorded_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(SERVER_HOME))

    assert (
        _remote_decision(
            "Read",
            {"file_path": str(ICLOUD_DOCUMENT)},
        )
        is Outcome.NOOP
    )
    seed_item_claim(conn, SESSION_ID, item_id=ITEM_ID)
    assert (
        _remote_decision(
            "Read",
            {"file_path": str(ICLOUD_DOCUMENT)},
        )
        is Outcome.NOOP
    )


def test_absolute_shell_read_uses_client_home_after_claim(
    conn,
    claimed_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(SERVER_HOME))

    decision = _remote_evaluation(
        "Bash", {"command": f"sed -n '1,40p' '{ICLOUD_DOCUMENT}'"},
    )
    assert decision.outcome is Outcome.NOOP, decision.message


@pytest.mark.parametrize(
    "target",
    [
        "~/.codex/skills/example/SKILL.md",
        str(CLIENT_HOME / ".codex/skills/example/SKILL.md"),
    ],
)
def test_sanctioned_installed_reads_expand_client_home(
    conn,
    claimed_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    monkeypatch.setenv("HOME", str(SERVER_HOME))

    assert _remote_decision("Read", {"file_path": target}) is Outcome.NOOP


@pytest.mark.parametrize(
    "target",
    [
        "~/.codex/attachments/input.png",
        str(CLIENT_HOME / ".codex/attachments/input.png"),
    ],
)
def test_home_derived_free_paths_expand_client_home(
    conn,
    claimed_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    monkeypatch.setenv("HOME", str(SERVER_HOME))

    assert (
        _remote_decision(
            "Write",
            {"file_path": target, "content": "asset"},
        )
        is Outcome.NOOP
    )


def test_missing_client_home_reproduces_claimed_reference_denial(
    conn,
    claimed_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(SERVER_HOME))

    assert (
        _remote_decision(
            "Read",
            {"file_path": str(ICLOUD_DOCUMENT)},
            include_home=False,
        )
        is Outcome.DENY
    )


@pytest.mark.parametrize(
    "target",
    [
        str(SERVER_HOME / "Documents/ref.md"),
        str(CLIENT_HOME / ".yoke/secrets/capability.token"),
        str(CLIENT_HOME / ".codex/auth.json"),
    ],
)
def test_server_home_and_client_secret_paths_stay_governed(
    conn,
    claimed_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    monkeypatch.setenv("HOME", str(SERVER_HOME))

    assert _remote_decision("Read", {"file_path": target}) is Outcome.DENY


def test_external_reference_authority_does_not_extend_to_writes(
    conn,
    claimed_worktree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(SERVER_HOME))

    assert (
        _remote_decision(
            "Write",
            {"file_path": str(ICLOUD_DOCUMENT), "content": "changed"},
        )
        is Outcome.DENY
    )
    assert (
        _remote_decision(
            "Bash",
            {
                "command": (
                    f"sed -n '1p' '{ICLOUD_DOCUMENT}' && "
                    f"cp '{ICLOUD_DOCUMENT}' '{ICLOUD_DOCUMENT}.bak'"
                )
            },
        )
        is Outcome.DENY
    )
