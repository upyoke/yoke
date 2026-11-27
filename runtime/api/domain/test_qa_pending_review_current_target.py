"""A pending review answers only for the execution target it captured.

A release successor reuses a requirement ID under a new execution target.
An older pending bundle frozen on the replaced target stays pending and
readable on its own execution, but it no longer blocks verdict writes or
names itself in the successor stage's wake line. A pending bundle on the
requirement's current target still blocks and is the one selected, even
when the historical bundle sorts first.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from runtime.api.domain.qa_capture_pending_review_test_support import (
    _acceptance,
    _seed_pending,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_run
from yoke_core.domain.qa_pending_agent_review import (
    pending_review_for_requirement,
    pending_review_requirements,
)

PENDING_TEXT = "independent agent review is pending"
HISTORICAL_DIGEST = "4" * 64


def _record_verdict(requirement_id: int, performed_by: str, verdict: str):
    payload: dict[str, Any] = {
        "performed_by": performed_by,
        "verdict": verdict,
        "verdict_reason": "Exact-target evidence reviewed.",
    }
    if performed_by == "human":
        payload["raw_result"] = json.dumps({"verification_tree": {"head_sha": "e" * 40}})
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        return qa_run.handle_qa_run_record_verdict(
            FunctionCallRequest(
                function="qa.run.record_verdict",
                actor=ActorContext(actor_id="2", session_id="capture-session"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
                payload=payload,
            )
        )


def _stop(conn: Any, execution_id: str) -> None:
    conn.execute(
        "UPDATE qa_plan_executions SET state='aborted' WHERE id=%s", (execution_id,)
    )


def _historical_bundle(conn: Any, execution: dict, requirement_id: int) -> str:
    """An older stopped execution on another target holding the same requirement."""
    row = dict(
        conn.execute(
            "SELECT * FROM qa_plan_executions WHERE id=%s", (execution["id"],)
        ).fetchone()
    )
    row.pop("execution_order", None)
    row.update(
        id="historical-" + str(execution["id"])[:24],
        state="aborted",
        execution_target_digest=HISTORICAL_DIGEST,
        created_at="2000-01-01T00:00:00Z",
    )
    columns = ",".join(row)
    conn.execute(
        f"INSERT INTO qa_plan_executions({columns}) "
        f"VALUES({','.join('%s' for _ in row)})",
        tuple(row.values()),
    )
    bundle_id = "historical-bundle"
    conn.execute(
        "INSERT INTO qa_plan_review_bundles "
        "(id,execution_id,roster_digest,bundle_digest,bundle_json,state,created_at) "
        "VALUES (%s,%s,%s,'captured',%s,'pending','2000-01-01T00:00:00Z')",
        (
            bundle_id,
            row["id"],
            row["roster_digest"],
            json.dumps({"cases": [{"requirement_id": requirement_id}]}),
        ),
    )
    conn.commit()
    return bundle_id


def test_successor_target_is_not_held_by_the_historical_review(test_db) -> None:
    run_id = "run-successor-target"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, "item")
    _stop(test_db, execution["id"])
    # The successor run took over the reused requirement on a new target; the
    # stopped execution stays frozen on the replaced one.
    test_db.execute(
        "UPDATE qa_plan_executions SET execution_target_digest=%s WHERE id=%s",
        (HISTORICAL_DIGEST, execution["id"]),
    )
    test_db.commit()

    assert pending_review_for_requirement(test_db, requirement_id) is None
    for stopped_only in (False, True):
        assert pending_review_requirements(
            test_db, [requirement_id], stopped_only=stopped_only
        ) == {}
    # The successor stage's wake line no longer names the old bundle.
    assert not any(
        bundle["bundle_id"] in line or str(execution["id"]) in line
        for line in _acceptance(test_db, run_id, "item").blockers
    )
    # The historical bundle is preserved, pending, on its own frozen target.
    kept = test_db.execute(
        "SELECT b.state,e.execution_target_digest FROM qa_plan_review_bundles b "
        "JOIN qa_plan_executions e ON e.id=b.execution_id WHERE b.id=%s",
        (bundle["bundle_id"],),
    ).fetchone()
    assert kept["state"] == "pending"
    assert kept["execution_target_digest"] == HISTORICAL_DIGEST
    # Successor writes are no longer refused by the historical review.
    recorded = _record_verdict(requirement_id, "human", "pass")
    assert recorded.primary_success, recorded.error


def test_same_target_review_blocks_even_when_history_sorts_first(test_db) -> None:
    run_id = "run-same-target"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, "item")
    historical = _historical_bundle(test_db, execution, requirement_id)

    held = pending_review_requirements(test_db, [requirement_id])[requirement_id]
    assert held.bundle_id == bundle["bundle_id"] != historical
    assert held.execution_target_digest == execution["execution_target_digest"]
    _stop(test_db, execution["id"])
    test_db.commit()
    stopped = pending_review_requirements(test_db, [requirement_id], stopped_only=True)
    assert stopped[requirement_id].bundle_id == bundle["bundle_id"]

    refused = _record_verdict(requirement_id, "agent", "pass")
    assert not refused.primary_success
    assert refused.error.code == "policy_violation"
    assert PENDING_TEXT in refused.error.message
    assert bundle["bundle_id"] in refused.error.message
    assert historical not in refused.error.message
    # The current-target bundle owns the stage's wake line too.
    blockers = _acceptance(test_db, run_id, "item").blockers
    assert any(bundle["bundle_id"] in line for line in blockers)
    assert not any(historical in line for line in blockers)
