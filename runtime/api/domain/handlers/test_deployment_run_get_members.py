"""deployment_runs.get answers who is in a run and its live carried work."""

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_no_obligation_member_close_out import _ready_member
from runtime.api.domain.test_run_success_member_settlement import _executing_run
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deployment_run_carried_work_read as carried_read
from yoke_core.domain.deployment_run_membership_removals import (
    record_membership_removals,
)
from yoke_core.domain.handlers.deployment_run_get import handle_deployment_run_get

RUN = "run-get-members"
LIVE = {"derivation": {"status": "derived", "source": "live"}, "items": []}


def _get(payload):
    return handle_deployment_run_get(
        deployment_request(
            function="deployment_runs.get",
            target=TargetRef(kind="workflow_run", workflow_run_id=RUN),
            payload=payload,
        )
    )


def _run_with_removal(conn):
    _project(conn)
    for item_id in (9931, 9932, 9933):
        _ready_member(conn, item_id, f"holder-{item_id}")
    _executing_run(conn, RUN, (9931, 9932, 9933))
    conn.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, 9932),
    )
    record_membership_removals(
        conn, RUN, [9932], reason="red member QA", session_id=None, actor_id=None
    )
    conn.commit()


def _live_carried_work(monkeypatch):
    carried_read._CACHE.clear()
    monkeypatch.setattr(
        carried_read, "derive_carried_work_safely", lambda _conn, _run: dict(LIVE)
    )


def test_selected_member_fields_name_members_and_removals(test_db, monkeypatch):
    _run_with_removal(test_db)
    _live_carried_work(monkeypatch)
    outcome = _get({"fields": ["status", "member_items", "membership_removals"]})
    assert outcome.primary_success, outcome.error
    run = outcome.result_payload["run"]
    assert list(run) == ["status", "member_items", "membership_removals"]
    assert run["status"] == "executing"
    assert [member["id"] for member in run["member_items"]] == [9931, 9933]
    assert all(member["ref"] for member in run["member_items"])
    (removal,) = run["membership_removals"]
    assert removal["id"] == 9932
    assert removal["reason"] == "red member QA"
    assert removal["removed_at"]


def test_a_recorded_removal_is_never_listed_as_a_member(test_db, monkeypatch):
    _run_with_removal(test_db)
    _live_carried_work(monkeypatch)
    record_membership_removals(
        test_db, RUN, [9933], reason="manual", session_id=None, actor_id=None
    )
    test_db.commit()
    outcome = _get({"field": "member_items"})
    assert outcome.primary_success, outcome.error
    assert [member["id"] for member in outcome.result_payload["value"]] == [9931]


def test_full_get_carries_computed_fields_and_live_carried_work(test_db, monkeypatch):
    _run_with_removal(test_db)
    _live_carried_work(monkeypatch)
    outcome = _get({})
    assert outcome.primary_success, outcome.error
    result = outcome.result_payload
    assert {"member_items", "membership_removals"} <= set(result["fields"])
    assert result["run"]["carried_work"] == LIVE
    assert [m["id"] for m in result["run"]["member_items"]] == [9931, 9933]
    recorded = test_db.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[0]
    assert not recorded


def test_single_carried_work_field_is_derived_live(test_db, monkeypatch):
    _run_with_removal(test_db)
    _live_carried_work(monkeypatch)
    outcome = _get({"field": "carried_work"})
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["value"] == LIVE


def test_unknown_field_names_the_computed_fields(test_db):
    _run_with_removal(test_db)
    outcome = _get({"fields": ["status", "members"]})
    assert not outcome.primary_success
    assert "member_items, membership_removals" in outcome.error.message
