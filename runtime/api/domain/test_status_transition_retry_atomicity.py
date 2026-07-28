"""Canonical status retry preconditions and preflight boundaries."""

from __future__ import annotations

import threading
from typing import Any

from runtime.api.domain.test_status_transition_preflight import (
    TARGET_STATUS,
    _actor_id,
    _isolate_status_effects,
    _publish_approval_workflow,
    _request,
)
from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import (
    backlog,
    backlog_update_op,
    qa_plan_attachments,
    workflow_status_transition_preflight,
)
from yoke_core.domain.handlers import lifecycle_transition


def test_invalid_target_is_rejected_before_qa_materialization(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    _publish_approval_workflow(
        test_db,
        label="Invalid status preflight",
        enabled=False,
    )
    item_id = 969
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    calls = 0

    def materialize(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(
        qa_plan_attachments,
        "materialize_for_item",
        materialize,
    )
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="not-a-stage",
        force=True,
        no_github=True,
        rebuild_board=False,
    )
    assert result["error_code"] == "VALIDATION_ERROR"
    assert calls == 0


def test_exceptional_transition_without_plan_attachment_skips_materialization(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    item_id = 971
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    calls = 0

    def materialize(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("unattached exceptional transition materialized")

    monkeypatch.setattr(
        qa_plan_attachments,
        "materialize_for_item",
        materialize,
    )
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="blocked",
        force=True,
        no_github=True,
        rebuild_board=False,
    )

    assert result["success"] is True
    assert calls == 0
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()[0]
    assert str(status) == "blocked"


def test_expected_source_status_survives_retry_after_status_drift(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    _publish_approval_workflow(
        test_db,
        label="Status retry source persistence",
        enabled=False,
    )
    item_id = 966
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    gate_calls = 0

    def count_gate(**_kwargs):
        nonlocal gate_calls
        gate_calls += 1
        return None

    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        count_gate,
    )
    original_preflight = workflow_status_transition_preflight.prepare_status_transition
    drifted = False

    def drift_after_first_preflight(conn, **kwargs):
        nonlocal drifted
        result = original_preflight(conn, **kwargs)
        if result.failure is None and not drifted:
            drifted = True
            conn.execute(
                "UPDATE items SET status='blocked' WHERE id=%s",
                (item_id,),
            )
            conn.commit()
        return result

    monkeypatch.setattr(
        workflow_status_transition_preflight,
        "prepare_status_transition",
        drift_after_first_preflight,
    )
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        expected_status="idea",
        force=True,
        no_github=True,
        rebuild_board=False,
    )

    assert result["error_code"] == "WORKFLOW_STATUS_PRECONDITION_FAILED"
    assert gate_calls == 0
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()[0]
    assert str(status) == "blocked"


def test_lifecycle_source_drift_rejects_before_preflight_artifacts(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    _publish_approval_workflow(
        test_db,
        label="Lifecycle source precondition",
        enabled=True,
    )
    item_id = 967
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    frozen_check_entered = threading.Event()
    continue_handler = threading.Event()
    outcome: dict[str, Any] = {}

    def pause_after_source_read(_item_id: int, _force: bool):
        frozen_check_entered.set()
        assert continue_handler.wait(timeout=10)
        return None

    monkeypatch.setattr(
        lifecycle_transition,
        "_frozen_blocked",
        pause_after_source_read,
    )
    request = _request(
        item_id=item_id,
        actor_id=_actor_id(test_db),
        lifecycle=True,
    ).model_copy(
        update={
            "payload": {
                "target_status": TARGET_STATUS,
                "source_status": "idea",
                "force": True,
            },
        },
    )

    def transition() -> None:
        outcome["result"] = lifecycle_transition.handle_transition(request)

    thread = threading.Thread(
        target=transition,
        name="lifecycle-source-preflight-boundary",
    )
    try:
        thread.start()
        assert frozen_check_entered.wait(timeout=10)
        test_db.execute(
            "UPDATE items SET status='blocked' WHERE id=%s",
            (item_id,),
        )
        test_db.commit()
    finally:
        continue_handler.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    result = outcome["result"]
    assert result.primary_success is False
    assert result.error is not None
    assert result.error.code == "precondition_failed"
    decision_count = test_db.execute(
        "SELECT COUNT(*) FROM decision_requests WHERE subject_key=%s",
        (f"{item_id}:{TARGET_STATUS}",),
    ).fetchone()[0]
    qa_count = test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE item_id=%s",
        (item_id,),
    ).fetchone()[0]
    assert (int(decision_count), int(qa_count)) == (0, 0)
