"""A settlement refusal is cheap, coded, names its real blocker, and is final.

A member still owing a blocking done obligation is never cleared, so the run
cannot succeed. Settlement must say so before staging any member's close,
name the open requirement rather than a generic unfinished close-out, and
carry its own error code so the driver stops instead of repeating a write
that answers the same way every time.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.test_run_success_member_settlement import (
    _executing_run,
    _run,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_core.domain import (
    delivery_member_close_steps,
    deploy_pipeline_control_plane as control_plane,
    deploy_pipeline_run_context as run_context,
)
from yoke_core.domain.deployment_run_settlement_refusal import (
    HELD_WITH_RUN,
    SETTLEMENT_BLOCKED_CODE,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.handlers.deployment_common import update_refusal_code
from yoke_core.domain.project_identity import render_item_ref

READY_ITEM = 9881
OWING_ITEM = 9882
REASON = "nothing observable once deployed"


def test_an_uncleared_member_refuses_before_any_member_is_staged(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    for item_id, holder in ((READY_ITEM, HOLDER_A), (OWING_ITEM, HOLDER_B)):
        _ready_member(test_db, item_id, holder)
        _no_obligation(test_db, item_id, reason=REASON)
    requirement = insert_qa_requirement(test_db, item_id=OWING_ITEM)
    test_db.commit()
    release = _status(test_db, READY_ITEM)
    _executing_run(test_db, "run-owing", (READY_ITEM, OWING_ITEM))

    def staged(*_args, **_kwargs):
        raise AssertionError("a refusing settlement must not stage any member")

    monkeypatch.setattr(delivery_member_close_steps, "stage_member_close", staged)

    refusal = cmd_update("run-owing", "status", "succeeded")

    assert refusal is not None
    assert update_refusal_code(refusal) == SETTLEMENT_BLOCKED_CODE
    owing = render_item_ref(test_db, OWING_ITEM)
    assert f"{owing}: its done gate still has 1 blocking QA requirement(s)" in refusal
    assert f"Requirement #{requirement['id']}" in refusal
    assert "its close-out has not completed" not in refusal
    assert f"{render_item_ref(test_db, READY_ITEM)}: {HELD_WITH_RUN}" in refusal
    assert _run(test_db, "run-owing") == ("executing", True)
    for item_id in (READY_ITEM, OWING_ITEM):
        assert _status(test_db, item_id) == release


def test_uncoded_update_refusals_keep_the_generic_code() -> None:
    assert update_refusal_code("Error: deployment run 'x' not found") == (
        "update_failed"
    )
    assert update_refusal_code("Error: candidate_containment_attestation_stale: x") == (
        "candidate_containment_attestation_stale"
    )


def _refusing_write(code: str, calls: list[str]):
    def write(run_id, field, value, **_kwargs):
        calls.append(f"{field}={value}")
        raise control_plane.DeploymentControlPlaneError(
            f"deployment_runs.execution.update failed: blocked {run_id}", code=code
        )

    return write


def test_a_settlement_refusal_is_not_retried(monkeypatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        control_plane,
        "update_run_field",
        _refusing_write(SETTLEMENT_BLOCKED_CODE, calls),
    )
    monkeypatch.setattr(run_context.time, "sleep", sleeps.append)

    with pytest.raises(run_context.RunFinalizationPending) as pending:
        run_context.finalize_run_success(
            "run-1", "flow", "yoke", [], "persistent", "stage"
        )

    assert calls == ["status=succeeded"]
    assert sleeps == []
    assert pending.value.code == SETTLEMENT_BLOCKED_CODE
    message = str(pending.value)
    assert f"refused ({SETTLEMENT_BLOCKED_CODE})" in message
    assert "blocked run-1" in message
    assert "control-plane connection" not in message
    assert "re-drive run-1 with `yoke watch deploy -- run-1` to finalize" not in message


def test_a_write_that_got_no_answer_is_retried(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        control_plane,
        "update_run_field",
        _refusing_write(TRANSPORT_FAILED_CODE, calls),
    )
    monkeypatch.setattr(run_context.time, "sleep", lambda *_: None)

    with pytest.raises(run_context.RunFinalizationPending) as pending:
        run_context.finalize_run_success(
            "run-1", "flow", "yoke", [], "persistent", "stage"
        )

    assert len(calls) == 3
    assert "restore the selected control-plane connection" in str(pending.value)
    assert "re-drive run-1 with `yoke watch deploy -- run-1` to finalize" in str(pending.value)


def test_a_re_drive_does_not_stamp_members_already_delivered(monkeypatch) -> None:
    from yoke_core.domain import deployment_item_stamp

    stamped: list[str] = []
    monkeypatch.setattr(
        deployment_item_stamp,
        "stamp_item_field",
        lambda ref, field, value: stamped.append(ref),
    )
    monkeypatch.setattr(
        run_context.run_updates, "update_run_field", lambda *_args: None
    )
    monkeypatch.setattr(run_context, "_emit_run_event", lambda *a, **k: None)
    members = {
        "YOK-1": {"status": "done", "deployed_to": "prod"},
        "YOK-2": {"status": "done", "deployed_to": "stage"},
        "YOK-3": {"status": "release", "deployed_to": "prod"},
    }

    run_context.finalize_run_success(
        "run-1",
        "flow",
        "yoke",
        ["YOK-1", "YOK-2", "YOK-3", "YOK-4"],
        "persistent",
        "prod",
        members=members,
    )

    assert stamped == ["YOK-2", "YOK-3", "YOK-4"]
