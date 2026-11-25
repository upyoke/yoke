"""Fresh walk admission uses the registered launch row."""

import sqlite3
from contextlib import closing

import pytest

from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain import qa_walk_launch_required as guard
from yoke_core.domain.qa_walk_launch_required import require_walk_launch


@pytest.fixture
def launches(monkeypatch):
    monkeypatch.setattr(guard, "ENFORCE_WALK_LAUNCH", True)
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(
            "CREATE TABLE session_launches (registered_session_id TEXT, "
            "native_session_id TEXT, item_id INTEGER, idempotency_key TEXT)"
        )
        yield conn


@pytest.mark.parametrize(
    ("registered_session", "item_id", "key"),
    [
        (None, None, "qa-walk:PLAN@SHA:-:KEY:1"),
        ("another-session", None, "qa-walk:PLAN@SHA:-:KEY:1"),
        ("runner", 19, "qa-walk:PLAN@SHA:-:KEY:1"),
        ("runner", None, "ordinary-launch"),
        ("runner", None, "QA-WALK:PLAN@SHA:-:KEY:1"),
        ("runner", None, None),
    ],
)
def test_walk_refuses_without_registered_itemless_walk_launch(
    launches, registered_session, item_id, key
):
    launches.execute(
        "INSERT INTO session_launches VALUES (?, ?, ?, ?)",
        (registered_session, "runner", item_id, key),
    )

    with pytest.raises(QaPlanExecutionStateError, match="qa_walk_needs_launched_session") as refusal:
        require_walk_launch(
            launches, [{"runner_id": "agent_mission", "verdict_path": "agent"}],
            session_id="runner",
        )

    body = str(refusal.value)
    assert "yoke qa plan partitions" in body
    assert "qa-walk:SUBJECT:SCOPE:KEY:ATTEMPT" in body
    assert "staff a relay machine serving claude-cli, codex-cli or cursor-cli" in body


@pytest.mark.parametrize(
    "case",
    [
        {"runner_id": "agent_mission", "verdict_path": "agent"},
        {"runner_id": "host_control", "verdict_path": "automatic"},
        {"runner_id": "worktree_run", "verdict_path": "automatic", "method_config": {"os": "macos"}},
    ],
)
def test_registered_itemless_walk_launch_admits_walk(launches, case):
    launches.execute(
        "INSERT INTO session_launches VALUES (?, ?, ?, ?)",
        ("walker", None, None, "qa-walk:ITEM:review:KEY:1"),
    )

    require_walk_launch(launches, [case], session_id="walker")


@pytest.mark.parametrize("runner", ["worktree_run", "ci_run", "browser_substrate"])
def test_automatic_hostless_partitions_need_no_launch(launches, runner):
    require_walk_launch(
        launches, [{"runner_id": runner, "verdict_path": "automatic"}],
        session_id="holder",
    )


def test_scoped_walk_resume_does_not_need_launch(launches, monkeypatch):
    monkeypatch.setattr(guard, "live_plan_execution_id", lambda *args, **kwargs: "live")
    monkeypatch.setattr(
        guard, "select_plan_execution", lambda *args, **kwargs: {"session_id": "owner"}
    )

    guard.require_scoped_walk_launch(
        launches, [{"runner_id": "agent_mission", "verdict_path": "agent"}],
        session_id="owner", item_id=19, transition_id="review", execution_target_digest="target",
    )


def test_scoped_walk_holder_cannot_freeze_fresh_walk(launches, monkeypatch):
    monkeypatch.setattr(guard, "live_plan_execution_id", lambda *args, **kwargs: None)
    with pytest.raises(guard.QaWalkNeedsLaunchedSession) as refusal:
        guard.require_scoped_walk_launch(
            launches, [{"runner_id": "agent_mission", "verdict_path": "agent"}],
            session_id="holder", item_id=19, transition_id="review", execution_target_digest="target",
        )
    assert refusal.value.code == "qa_walk_needs_launched_session"
