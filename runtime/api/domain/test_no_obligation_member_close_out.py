"""A recorded no-obligation member closes without a wake.

Auto-close keys on the authored ``post_deploy_no_obligation`` fact. An
empty case set stays held. The waiver-backed ``declared_none`` still
wakes, because a waiver is not that fact.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
    _run,
)
from runtime.api.domain.test_deployment_qa_member_acceptance_notice import (
    _executing_run,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _recipients,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.post_deploy_verification_answer import (
    DECLARATION_QA_KIND,
    NO_OBLIGATION_QA_KIND,
)
from yoke_core.domain.work_claim_target_sql import scope_int_sql


NO_OBLIGATION_ITEM = 9821
SIBLING_ITEM = 9822
DECLARED_NONE_ITEM = 9823
UNANSWERED_ITEM = 9824
MISSING_EVIDENCE_ITEM = 9825
ITEM_QA_MEMBER = 9826


def _no_obligation(conn: Any, item_id: int, *, reason: str) -> None:
    insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind=NO_OBLIGATION_QA_KIND,
        qa_phase="post_deploy",
        blocking_mode="non_blocking",
        instructions=reason,
    )


def _declared_none(conn: Any, item_id: int) -> None:
    insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind=DECLARATION_QA_KIND,
        qa_phase="post_deploy",
        blocking_mode="non_blocking",
        waived_at=iso8601_now(),
        waiver_rationale="operator declined the check",
        waiver_source="owner",
    )


def _landing_evidence(conn: Any, item_id: int) -> None:
    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="Landed the member.",
        verification_summary="nothing observable once deployed",
        verification_status="passed",
        commit_sha="a" * 40,
        merge_sha="b" * 40,
        touched_files=["src/member.py"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="a" * 40,
    )


def _ready_member(conn: Any, item_id: int, holder: str) -> None:
    _member_at_release_wait(conn, item_id)
    _parked_owner(conn, holder, item_id)
    _landing_evidence(conn, item_id)


def test_recorded_no_obligation_closes_without_waking(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, NO_OBLIGATION_ITEM, HOLDER_A)
    _no_obligation(
        test_db, NO_OBLIGATION_ITEM, reason="nothing observable once deployed"
    )
    _run(
        test_db,
        "run-no-obligation",
        flow=COMPLETION_FLOW,
        members=(NO_OBLIGATION_ITEM,),
    )

    [report] = notify_delivery_cleared(test_db, run_id="run-no-obligation")

    assert report["delivery"] == "closed"
    assert (
        _recipients(
            test_db,
            delivery_cleared_idempotency_key(NO_OBLIGATION_ITEM, "run-no-obligation"),
        )
        == []
    )
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (NO_OBLIGATION_ITEM,)
    ).fetchone()["status"]
    assert status == "done"
    item_scope = scope_int_sql(test_db, "scope", "item_id")
    live = test_db.execute(
        "SELECT id FROM work_claims WHERE target_kind='item' "
        f"AND released_at IS NULL AND {item_scope}=%s",
        (NO_OBLIGATION_ITEM,),
    ).fetchone()
    assert live is None
    holder_session = test_db.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s",
        (HOLDER_A,),
    ).fetchone()
    assert holder_session is not None and holder_session["ended_at"] is not None


def test_a_sibling_that_owes_a_check_is_still_woken(test_db: Any, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, NO_OBLIGATION_ITEM, HOLDER_A)
    _ready_member(test_db, SIBLING_ITEM, HOLDER_B)
    _no_obligation(test_db, NO_OBLIGATION_ITEM, reason="no runtime surface")
    _run(
        test_db,
        "run-mixed",
        flow=COMPLETION_FLOW,
        members=(NO_OBLIGATION_ITEM, SIBLING_ITEM),
    )

    reports = {
        row["public_ref"][-4:]: row["delivery"]
        for row in notify_delivery_cleared(test_db, run_id="run-mixed")
    }

    assert reports["9821"] == "closed"
    assert reports["9822"] in ("delivered", "undelivered")
    assert (
        _recipients(
            test_db, delivery_cleared_idempotency_key(NO_OBLIGATION_ITEM, "run-mixed")
        )
        == []
    )
    assert _recipients(
        test_db, delivery_cleared_idempotency_key(SIBLING_ITEM, "run-mixed")
    ) == [HOLDER_B]
    statuses = {
        int(row["id"]): str(row["status"])
        for row in test_db.execute(
            "SELECT id, status FROM items WHERE id IN (%s,%s)",
            (NO_OBLIGATION_ITEM, SIBLING_ITEM),
        )
    }
    assert statuses[NO_OBLIGATION_ITEM] == "done"
    assert statuses[SIBLING_ITEM] != "done"


def test_declared_none_still_wakes(test_db: Any, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, DECLARED_NONE_ITEM, HOLDER_A)
    _declared_none(test_db, DECLARED_NONE_ITEM)
    _run(
        test_db,
        "run-declared-none",
        flow=COMPLETION_FLOW,
        members=(DECLARED_NONE_ITEM,),
    )

    [report] = notify_delivery_cleared(test_db, run_id="run-declared-none")

    assert report["delivery"] in ("delivered", "undelivered")
    assert _recipients(
        test_db,
        delivery_cleared_idempotency_key(DECLARED_NONE_ITEM, "run-declared-none"),
    ) == [HOLDER_A]
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (DECLARED_NONE_ITEM,)
    ).fetchone()["status"]
    assert status != "done"


def test_an_unanswered_member_still_wakes(test_db: Any, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, UNANSWERED_ITEM, HOLDER_A)
    _run(
        test_db,
        "run-unanswered",
        flow=COMPLETION_FLOW,
        members=(UNANSWERED_ITEM,),
    )

    [report] = notify_delivery_cleared(test_db, run_id="run-unanswered")

    assert report["delivery"] in ("delivered", "undelivered")
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (UNANSWERED_ITEM,)
    ).fetchone()["status"]
    assert status != "done"


def test_missing_landing_evidence_sends_a_recovery_wake(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _member_at_release_wait(test_db, MISSING_EVIDENCE_ITEM)
    _parked_owner(test_db, HOLDER_A, MISSING_EVIDENCE_ITEM)
    _no_obligation(test_db, MISSING_EVIDENCE_ITEM, reason="nothing to observe")
    _run(
        test_db,
        "run-missing-evidence",
        flow=COMPLETION_FLOW,
        members=(MISSING_EVIDENCE_ITEM,),
    )

    [report] = notify_delivery_cleared(test_db, run_id="run-missing-evidence")

    assert report["delivery"].startswith("failed:")
    assert "execution_evidence" in report["delivery"]
    key = delivery_cleared_idempotency_key(
        MISSING_EVIDENCE_ITEM, "run-missing-evidence"
    )
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert "Automatic close-out failed" in body
    assert "execution_evidence" in body
    assert "yoke merge item" in body
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (MISSING_EVIDENCE_ITEM,)
    ).fetchone()["status"]
    assert status != "done"


def test_item_qa_acceptance_does_not_wake_a_no_obligation_member(
    test_db: Any,
) -> None:
    _executing_run(
        test_db, "run-item-qa-none", (ITEM_QA_MEMBER,), plan_slug="wake-none"
    )
    _no_obligation(test_db, ITEM_QA_MEMBER, reason="nothing observable once deployed")
    accepted = deployment_qa_stage_status(
        test_db,
        run_id="run-item-qa-none",
        stage_name="item-qa",
        member_item_id=ITEM_QA_MEMBER,
    )

    assert accepted["accepted"] is True
    assert (
        _recipients(
            test_db,
            item_qa_accepted_idempotency_key(ITEM_QA_MEMBER, "run-item-qa-none"),
        )
        == []
    )
