"""Relayed watcher-capture authority regressions for session-cwd lint."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.hooks.types import HookContext, Outcome
from yoke_contracts.hook_runner.session_cwd import (
    CLIENT_CLAUDE_JOB_TMP_KEY,
    CLIENT_CLAUDE_JOB_TMP_SCHEMA,
    CLIENT_SCRATCH_ROOT_KEY,
    CLIENT_SCRATCH_ROOT_SCHEMA,
    client_claude_job_tmp,
    client_claude_job_tmp_fact,
    client_scratch_root,
    client_scratch_root_fact,
)
from yoke_core.domain import lint_session_cwd
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
)


SESSION_ID = "session-owner"
CLIENT_ROOT = Path.home() / ".yoke" / "tmp"
CLAUDE_JOB_DIR = Path.home() / ".claude" / "jobs" / "job-123"


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


def _capture(stream: str, *, session_id: str = SESSION_ID) -> Path:
    return (
        CLIENT_ROOT
        / "1"
        / "sessions"
        / session_id
        / "runs"
        / "pid-444"
        / "watcher-captures"
        / f"yoke-merge.{stream}.abc123.log"
    )


def _remote_decision(
    tool_name: str, tool_input: dict, *, include_job_tmp: bool = False,
) -> Outcome:
    payload = {
        "session_id": SESSION_ID,
        "tool_name": tool_name,
        "tool_input": tool_input,
        **client_scratch_root_fact(str(CLIENT_ROOT)),
    }
    if include_job_tmp:
        payload.update(client_claude_job_tmp_fact(str(CLAUDE_JOB_DIR)))
    decision = lint_session_cwd.evaluate(HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name,
        session_id=SESSION_ID,
        remote=True,
    ))
    return decision.outcome


@pytest.mark.parametrize("root", ["relative/root", str(Path(CLIENT_ROOT.anchor))])
def test_client_root_contract_rejects_non_scoped_roots(root: str) -> None:
    assert client_scratch_root({
        CLIENT_SCRATCH_ROOT_KEY: {
            "schema": CLIENT_SCRATCH_ROOT_SCHEMA,
            "root": root,
        }
    }) == ""


def test_client_job_tmp_contract_is_bounded() -> None:
    fact = client_claude_job_tmp_fact(str(CLAUDE_JOB_DIR))
    assert fact == {
        CLIENT_CLAUDE_JOB_TMP_KEY: {
            "schema": CLIENT_CLAUDE_JOB_TMP_SCHEMA,
            "root": str(CLAUDE_JOB_DIR / "tmp"),
        }
    }
    assert client_claude_job_tmp(fact) == str(CLAUDE_JOB_DIR / "tmp")
    assert client_claude_job_tmp(
        {}, job_dir=str(CLAUDE_JOB_DIR),
    ) == str(CLAUDE_JOB_DIR / "tmp")
    assert client_claude_job_tmp({
        CLIENT_CLAUDE_JOB_TMP_KEY: {
            "schema": CLIENT_CLAUDE_JOB_TMP_SCHEMA,
            "root": str(CLAUDE_JOB_DIR),
        }
    }) == ""


def test_relay_allows_background_launch_and_failure_capture_reads(
    conn, claimed_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    server_root = tmp_path / "server-scratch"
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(server_root))
    raw = _capture("raw")
    progress = _capture("progress")
    launch = (
        f"cd {claimed_worktree} && yoke watch merge "
        f"--raw-capture {raw} --progress-capture {progress} -- "
        "merge-item YOK-2106"
    )
    launch_targets = extract_command_targets(launch)

    assert str(raw) in launch_targets
    assert str(progress) in launch_targets
    assert extract_command_targets(f"tail -80 {raw}") == [str(raw)]

    assert _remote_decision(
        "Bash", {"command": launch, "run_in_background": True},
    ) is Outcome.NOOP
    assert _remote_decision(
        "Bash", {"command": f"tail -80 {raw}"},
    ) is Outcome.NOOP
    assert _remote_decision(
        "Read", {"file_path": str(raw)},
    ) is Outcome.NOOP


def test_relay_without_client_root_reproduces_scope_denial(
    conn, claimed_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "server-scratch"))
    payload = {
        "session_id": SESSION_ID,
        "tool_name": "Read",
        "tool_input": {"file_path": str(_capture("raw"))},
    }

    decision = lint_session_cwd.evaluate(HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name="Read",
        session_id=SESSION_ID,
        remote=True,
    ))

    assert decision.outcome is Outcome.DENY


def test_relay_rejects_another_sessions_capture(
    conn, claimed_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "server-scratch"))

    assert _remote_decision(
        "Read", {"file_path": str(_capture("raw", session_id="other"))},
    ) is Outcome.DENY


def test_relay_keeps_other_client_scratch_subtrees_claim_gated(
    conn, claimed_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "server-scratch"))
    dispatch_input = (
        CLIENT_ROOT / "1" / "sessions" / SESSION_ID / "runs" / "pid-444"
        / "dispatch-inputs" / "prompt.md"
    )

    assert _remote_decision(
        "Read", {"file_path": str(dispatch_input)},
    ) is Outcome.DENY


def test_relay_allows_only_the_evidenced_background_job_tmp(
    conn, claimed_worktree: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "server-scratch"))
    target = CLAUDE_JOB_DIR / "tmp" / "verification.log"

    assert _remote_decision(
        "Bash", {"command": f"touch {target}"}, include_job_tmp=True,
    ) is Outcome.NOOP
    assert _remote_decision(
        "Bash", {"command": f"touch {target}"}, include_job_tmp=False,
    ) is Outcome.DENY
    assert _remote_decision(
        "Bash",
        {"command": f"touch {CLAUDE_JOB_DIR / 'result.json'}"},
        include_job_tmp=True,
    ) is Outcome.DENY
