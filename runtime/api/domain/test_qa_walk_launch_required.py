"""Fresh walk admission uses the registered launch row."""

import sqlite3
from contextlib import closing

import pytest

from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain import qa_walk_launch_required as guard
from yoke_core.domain.qa_walk_launch_required import require_walk_launch


@pytest.fixture
def launches():
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
    assert "launch create --project P --level LEVEL" in body
    assert "skip claim acquisition and use delegated QA access" in body
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


def test_registered_desktop_can_start_and_resume_its_standalone_walk():
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session
    from runtime.api.domain.qa_plan_standalone_execution_test_support import _begin
    from runtime.api.fixtures.pg_testdb import test_database
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

    with test_database() as conn:
        plan = create_plan(conn, project="yoke", slug="manual-proof", name="Manual proof")
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[{
                "case_key": "observe-context",
                "method_id": "exploratory-mission",
                "instructions": "Observe the controller context",
                "expected_outcome": "The controller has the declared context",
                "method_config": {"executor": "informed_subagent"},
            }],
        )
        seed_qa_session(conn, "manual-owner", actor_id=7)
        conn.execute(
            "UPDATE harness_sessions SET executor_surface='codex-desktop' WHERE session_id=%s",
            ("manual-owner",),
        )
        conn.commit()
        assert conn.execute(
            "SELECT 1 FROM session_launches WHERE registered_session_id=%s",
            ("manual-owner",),
        ).fetchone() is None

        first = _begin(conn)
        assert first["session_id"] == "manual-owner"
        assert str(first["actor_id"]) == "7"
        assert _begin(conn)["id"] == first["id"]
