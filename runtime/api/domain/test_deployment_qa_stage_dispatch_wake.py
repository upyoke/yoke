"""dispatch_deployment_qa_stage wakes an item's claim holder while waiting."""

from __future__ import annotations

from typing import Any
from unittest import mock

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key
from yoke_core.domain.work_claim_targets import make_item_target


def _run(conn: Any, run_id: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "VALUES (%s,1,'flow-x','executing',%s)",
        (run_id, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


def _member(conn: Any, run_id: str, item_id: int) -> None:
    insert_item(conn, id=item_id, project_sequence=item_id, workflow_id="issue")
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,%s)",
        (run_id, item_id, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


_WAITING = {"accepted": False, "reasons": ["awaiting agent verdict"], "request_id": None}
_ACCEPTED = {"accepted": True, "reasons": [], "request_id": None}


def _patched(*, status, materialize_ok: bool = True):
    patches = [
        mock.patch("yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status", return_value=status),
    ]
    if materialize_ok:
        patches.append(
            mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage")
        )
    return patches


def test_wakes_the_waiting_members_claim_holder(test_db: Any) -> None:
    _run(test_db, "run-wake-1")
    _member(test_db, "run-wake-1", 9601)
    stage = {"name": "item-qa", "scope": "item"}

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status", return_value=_WAITING
        ),
        mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage"),
        mock.patch.object(
            dispatch_mod, "notify_item_scoped_qa_wait", return_value="delivered"
        ) as notify,
    ):
        rc, diag = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id="run-wake-1")

    assert rc == -4
    assert "awaiting agent verdict" in diag
    notify.assert_called_once()
    assert notify.call_args.kwargs["run_id"] == "run-wake-1"
    assert notify.call_args.kwargs["stage_name"] == "item-qa"
    assert notify.call_args.kwargs["item_id"] == 9601
    assert notify.call_args.kwargs["project_id"] == 1
    assert "awaiting agent verdict" in notify.call_args.kwargs["reasons"]


def test_accepted_member_is_never_woken(test_db: Any) -> None:
    _run(test_db, "run-wake-2")
    _member(test_db, "run-wake-2", 9602)
    stage = {"name": "item-qa", "scope": "item"}

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status", return_value=_ACCEPTED
        ),
        mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage"),
        mock.patch.object(dispatch_mod, "notify_item_scoped_qa_wait") as notify,
    ):
        rc, _diag = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id="run-wake-2")

    assert rc == 0
    notify.assert_not_called()


def test_run_scoped_waiting_stage_wakes_the_run_driver(test_db: Any) -> None:
    """Run scope has no single item to wake, so it addresses the project's
    deploy-lock driver (or steering) instead of an item claim holder."""
    _run(test_db, "run-wake-3")
    stage = {"name": "run-qa", "scope": "run"}

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status", return_value=_WAITING
        ),
        mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage"),
        mock.patch.object(dispatch_mod, "notify_item_scoped_qa_wait") as item_notify,
        mock.patch.object(
            dispatch_mod, "notify_run_scoped_qa_wait", return_value="delivered"
        ) as run_notify,
    ):
        rc, diag = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id="run-wake-3")

    assert rc == -4
    assert "run: awaiting agent verdict" in diag
    item_notify.assert_not_called()
    run_notify.assert_called_once()
    assert run_notify.call_args.kwargs["run_id"] == "run-wake-3"
    assert run_notify.call_args.kwargs["stage_name"] == "run-qa"
    assert run_notify.call_args.kwargs["project_id"] == 1
    assert "awaiting agent verdict" in run_notify.call_args.kwargs["reasons"]


def test_run_scoped_wait_with_no_recipient_is_reported_visibly(
    test_db: Any, capsys
) -> None:
    _run(test_db, "run-wake-5")
    stage = {"name": "run-qa", "scope": "run"}

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status", return_value=_WAITING
        ),
        mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage"),
        mock.patch.object(
            dispatch_mod, "notify_run_scoped_qa_wait", return_value=""
        ),
    ):
        rc, diag = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id="run-wake-5")

    assert rc == -4
    assert "run: awaiting agent verdict" in diag
    out = capsys.readouterr().out
    assert "no deploy-lock driver" in out
    assert "Staff it manually" in out


def test_a_same_run_repeat_dispatch_re_attempts_notify_every_poll(
    test_db: Any,
) -> None:
    """The pipeline re-polls a waiting stage repeatedly within one run;
    dispatch tries to notify on every poll (the real recipient/message
    path, not mocked) rather than remembering "already tried once" for
    itself. A second attempt with different reasons text is a harmless
    dedupe at the message layer -- covered directly in
    test_deployment_qa_stage_wake_delivery.py -- not a dispatch-level
    collision."""
    _project(test_db)
    _run(test_db, "run-wake-6")
    item_id = 9606
    _member(test_db, "run-wake-6", item_id)
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    stage = {"name": "item-qa", "scope": "item"}
    key = stage_wait_idempotency_key("run-wake-6", "item-qa", item_id)

    with mock.patch(
        "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
        return_value={
            "accepted": False,
            "reasons": ["2 of 3 requirements outstanding"],
            "request_id": None,
        },
    ), mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage"):
        first = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id="run-wake-6")

    with mock.patch(
        "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
        return_value={
            "accepted": False,
            "reasons": ["1 of 3 requirements outstanding"],
            "request_id": None,
        },
    ), mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage"):
        second = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id="run-wake-6")

    assert first[0] == -4 and second[0] == -4
    assert "2 of 3" in first[1]
    assert "1 of 3" in second[1]
    # Both polls attempted delivery; the message store kept exactly the
    # first one under the stable (run, stage, item) key.
    assert _recipients(test_db, key) == [HOLDER_A]


def test_a_wake_failure_degrades_without_losing_the_wait_result(
    test_db: Any, capsys
) -> None:
    _run(test_db, "run-wake-4")
    _member(test_db, "run-wake-4", 9604)
    stage = {"name": "item-qa", "scope": "item"}

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status", return_value=_WAITING
        ),
        mock.patch("yoke_core.domain.deployment_qa_stage_materialization.materialize_deployment_qa_stage"),
        mock.patch.object(
            dispatch_mod,
            "notify_item_scoped_qa_wait",
            side_effect=RuntimeError("message service unavailable"),
        ),
    ):
        rc, diag = materialize_and_gate_deployment_qa_stage(test_db, stage, run_id="run-wake-4")

    assert rc == -4
    assert "awaiting agent verdict" in diag
    out = capsys.readouterr().out
    assert "could not wake a recipient for run" in out
    assert "member 9604" in out
