"""Walk-end disposes of the projects its execution created, and nothing else."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    OpenFixtureConnection,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain import test_agent_mission_cleanup as cleanup_support
from runtime.api.domain.test_agent_mission_qa import (
    ACTOR,
    _materialize_mission,
    _request,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.agent_mission_project_disposal import (
    FUNCTION_ID,
    handle_mission_project_disposal,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import prepare_agent_mission_contract
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.yoke_function_dispatch_qa_claims import qa_subject_claim_verdict

ITEM = 7861
FIXTURE, REAL = 930, 931
HOST_SESSION = "host-walk-session"
removed_mission = cleanup_support.removed_mission


@pytest.fixture(autouse=True)
def item_close_shares_the_fixture_connection(test_db, monkeypatch):
    """Item close binds connect at import, before the fixture patches it."""
    monkeypatch.setattr(
        "yoke_core.domain.backlog_close_op.connect",
        lambda *_args, **_kwargs: OpenFixtureConnection(test_db),
    )


@pytest.fixture
def walking_mission(test_db, tmp_path, monkeypatch):
    """A mission parked for its walk, as walk-end finds it."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement = _materialize_mission(test_db, item_id=ITEM)
    execution = begin_plan_execution(
        test_db,
        item_id=ITEM,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    request = _request(
        "test_machine.plan_case.begin",
        item_id=ITEM,
        execution_id=str(execution["id"]),
        requirement_id=requirement,
        ordinal=0,
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        prepared = prepare_agent_mission_contract(begun.result_payload["execution"])
    finally:
        clear_host_control_factory()
    ready = handle_agent_mission_ready(
        request.model_copy(
            update={
                "function": "test_machine.mission.ready",
                "payload": {**request.payload, **prepared},
            }
        )
    )
    assert ready.primary_success, ready.error
    begin_plan_review(test_db, lock_plan_execution(test_db, str(execution["id"])))
    test_db.commit()
    return request.model_copy(
        update={
            "payload": {
                "execution_id": str(execution["id"]),
                "requirement_id": requirement,
                "run_id": ready.result_payload["result"]["run_id"],
            }
        }
    )


def _project(conn, project_id: int, slug: str, created_at) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (project_id, slug, slug.title(), slug[:3].upper(), created_at),
    )
    conn.commit()


def _walk_created_projects(conn) -> None:
    """The walk installed cedar with work in flight; oak predates the walk."""
    now = utc_now()
    _project(conn, FIXTURE, "cedar", instant_parameter(conn, now))
    _project(conn, REAL, "oak", instant_parameter(conn, now - timedelta(days=30)))
    insert_item(
        conn, id=9301, project="cedar", workflow_id="dash", status="implementing"
    )
    insert_item(conn, id=9302, project="cedar", workflow_id="dash", status="idea")
    insert_item(conn, id=9311, project="oak", workflow_id="dash", status="idea")
    insert_item_worktree(conn, item_id=9301, branch="CED-1", path="/host/cedar/lane")
    insert_session(conn, session_id=HOST_SESSION)
    insert_item_claim(conn, session_id=HOST_SESSION, item_id=9301)
    conn.commit()


def _dispose(request, host_project_ids):
    return handle_mission_project_disposal(
        request.model_copy(
            update={
                "function": FUNCTION_ID,
                "payload": {
                    **request.payload,
                    "host_projects": [
                        {"project_id": project_id, "checkout": f"/host/{project_id}"}
                        for project_id in host_project_ids
                    ],
                },
            }
        )
    )


def _state(conn) -> dict:
    def one(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    state = {
        "statuses": {
            item: one("SELECT status FROM items WHERE id=%s", item)
            for item in (9301, 9302, 9311)
        },
        "lane": one("SELECT state FROM item_worktrees WHERE item_id=9301"),
        "claim_open": one(
            "SELECT COUNT(*) FROM work_claims WHERE session_id=%s AND released_at IS NULL",
            HOST_SESSION,
        ),
        "retired": {
            pid: one("SELECT retired_at FROM projects WHERE id=%s", pid) is not None
            for pid in (FIXTURE, REAL)
        },
    }
    conn.rollback()
    return state


def _assert_only_the_fixture_was_disposed(conn, outcome) -> None:
    assert outcome.primary_success, outcome.error
    dispositions = {
        entry["project_id"]: entry["disposition"]
        for entry in outcome.result_payload["projects"]
    }
    assert dispositions == {
        FIXTURE: "retired",
        REAL: "not_created_by_execution",
    }, outcome.result_payload
    assert outcome.result_payload["unsettled"] == []
    assert _state(conn) == {
        "statuses": {9301: "cancelled", 9302: "cancelled", 9311: "idea"},
        "lane": "released",
        "claim_open": 0,
        "retired": {FIXTURE: True, REAL: False},
    }
    receipt = conn.execute(
        "SELECT metadata FROM qa_artifacts WHERE artifact_type='fixture_project_disposal'"
    ).fetchone()[0]
    conn.rollback()
    assert json.loads(receipt) == {"project_ids": [FIXTURE, REAL]}


def test_walk_end_disposes_of_the_project_its_walk_created(test_db, walking_mission):
    _walk_created_projects(test_db)

    outcome = _dispose(walking_mission, [FIXTURE, REAL])

    _assert_only_the_fixture_was_disposed(test_db, outcome)


def test_aborted_walk_end_disposes_of_the_project_its_walk_created(
    test_db, removed_mission
):
    cleanup, _control, _original = removed_mission
    _walk_created_projects(test_db)
    request = cleanup.model_copy(
        update={
            "function": FUNCTION_ID,
            "payload": {
                key: cleanup.payload[key]
                for key in ("execution_id", "requirement_id", "run_id")
            },
        }
    )
    assert qa_subject_claim_verdict(request) == (True, None, None)

    outcome = _dispose(request, [FIXTURE, REAL])

    _assert_only_the_fixture_was_disposed(test_db, outcome)


def test_rerun_after_the_host_reset_still_reaches_receipted_projects(
    test_db, walking_mission
):
    _walk_created_projects(test_db)
    test_db.execute("UPDATE items SET merged_at=%s WHERE id=9301", (utc_now(),))
    test_db.commit()
    first = _dispose(walking_mission, [FIXTURE])
    assert [entry["disposition"] for entry in first.result_payload["unsettled"]] == [
        "blocked"
    ]
    test_db.execute("UPDATE items SET merged_at=NULL WHERE id=9301")
    test_db.commit()

    rerun = _dispose(walking_mission, [])

    assert rerun.primary_success, rerun.error
    assert rerun.result_payload["projects"][0]["disposition"] == "retired"
    assert _state(test_db)["retired"] == {FIXTURE: True, REAL: False}


def test_only_the_executions_own_session_may_dispose(test_db, walking_mission):
    _walk_created_projects(test_db)
    stranger = walking_mission.model_copy(
        update={"actor": ActorContext(actor_id="1", session_id="another-session")}
    )

    outcome = _dispose(stranger, [FIXTURE])

    assert not outcome.primary_success
    assert "mission_project_disposal_owner_required" in outcome.error.message
    assert _state(test_db)["retired"] == {FIXTURE: False, REAL: False}


def test_a_project_the_host_does_not_map_is_never_touched(test_db, walking_mission):
    _walk_created_projects(test_db)

    outcome = _dispose(walking_mission, [])

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["projects"] == []
    assert _state(test_db)["retired"] == {FIXTURE: False, REAL: False}
    assert _state(test_db)["statuses"][9302] == "idea"


def test_a_project_the_actor_does_not_administer_is_left_and_settled(
    test_db, walking_mission, monkeypatch
):
    from yoke_core.domain import machine_access_authority

    _walk_created_projects(test_db)
    monkeypatch.setattr(
        machine_access_authority, "actor_administers_project", lambda *a, **k: False
    )

    outcome = _dispose(walking_mission, [FIXTURE])

    # No rerun can change it, so walk-end finishes and names it instead.
    assert outcome.result_payload["unsettled"] == []
    assert [e["slug"] for e in outcome.result_payload["left_for_administrator"]] == [
        "cedar"
    ]
    assert _state(test_db)["statuses"][9302] == "idea"
    assert _state(test_db)["retired"] == {FIXTURE: False, REAL: False}


def test_an_ended_execution_disposes_of_nothing(test_db, walking_mission):
    _walk_created_projects(test_db)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='completed' WHERE id=%s",
        (walking_mission.payload["execution_id"],),
    )
    test_db.commit()

    outcome = _dispose(walking_mission, [FIXTURE])

    assert not outcome.primary_success
    assert "mission_project_disposal_execution_ended" in outcome.error.message
    assert _state(test_db)["retired"] == {FIXTURE: False, REAL: False}


def test_an_unrecordable_receipt_disposes_of_nothing(
    test_db, walking_mission, monkeypatch
):
    from yoke_core.domain.handlers import qa_artifact_add
    from yoke_core.domain.handlers.machine_qa import _failure

    _walk_created_projects(test_db)
    monkeypatch.setattr(
        qa_artifact_add,
        "handle_qa_artifact_add",
        lambda request: _failure("artifact_storage_unavailable", "store down"),
    )

    outcome = _dispose(walking_mission, [FIXTURE])

    assert not outcome.primary_success
    assert "mission_project_disposal_unrecorded" in outcome.error.message
    assert _state(test_db)["statuses"][9302] == "idea"
    assert _state(test_db)["retired"] == {FIXTURE: False, REAL: False}


def test_an_id_this_control_plane_lacks_settles_as_not_found(test_db, walking_mission):
    outcome = _dispose(walking_mission, [987654])

    assert outcome.primary_success, outcome.error
    assert [e["disposition"] for e in outcome.result_payload["projects"]] == [
        "not_found"
    ]
    assert outcome.result_payload["unsettled"] == []
