"""Explicitly discharged members can finish while sibling QA holds a run."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
)
from runtime.api.domain.test_independent_member_delivery_close_out import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _status,
)
from runtime.api.domain.test_no_obligation_member_close_out import _no_obligation
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_member_independent_close_out import (
    independent_member_delivery_ready,
)
from yoke_core.domain.item_json_sections import upsert_json_section


def test_no_obligation_member_closes_while_sibling_qa_holds_run(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-independent-no-obligation"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _no_obligation(test_db, MEMBER_A, reason="nothing observable after delivery")
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER_B,
    )

    assert independent_member_delivery_ready(test_db, item_id=MEMBER_A, run_id=run_id)
    accepted = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=MEMBER_A
    )

    assert accepted["accepted"] is True
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "done",
        "release",
    )
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
        == "executing"
    )
    assert (
        test_db.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (HOLDER_A,)
        ).fetchone()["ended_at"]
        is not None
    )
    assert (
        test_db.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (HOLDER_B,)
        ).fetchone()["ended_at"]
        is None
    )
    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=MEMBER_A
    )["accepted"]
    assert _status(test_db, MEMBER_A) == "done"


def test_shared_run_qa_holds_explicitly_discharged_member(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-shared-no-obligation"
    _seed_final_run(test_db, run_id, shared_qa=True)
    _no_obligation(test_db, MEMBER_A, reason="nothing observable after delivery")

    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=MEMBER_A
    )["accepted"]
    assert not independent_member_delivery_ready(
        test_db, item_id=MEMBER_A, run_id=run_id
    )
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "release",
        "release",
    )


def test_close_out_refusal_sends_named_recovery_notice(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-no-obligation-missing-evidence"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _no_obligation(test_db, MEMBER_A, reason="nothing observable after delivery")
    upsert_json_section(
        test_db,
        item_id=MEMBER_A,
        section=DASH_EVIDENCE_SECTION,
        payload={},
        ordering=190,
    )
    test_db.commit()

    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=MEMBER_A
    )["accepted"]
    assert _status(test_db, MEMBER_A) == "release"
    [body] = _bodies(test_db, item_qa_accepted_idempotency_key(MEMBER_A, run_id))
    assert "Automatic close-out failed" in body
    assert "result_summary" in body
    assert "yoke merge item" in body
