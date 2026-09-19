"""Recording a merge must not require the delivery still being awaited.

An item whose flow names a real target tier delivers through a release, and
its first close-out is what sets that flow. Every later landing on the same
item then asked the evidence write for a delivery that had not happened yet
-- the very delivery its release wait exists to await -- so a re-landed item
could not record the merge it had just made.
"""

from __future__ import annotations

import json
from contextlib import nullcontext

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    OBLIGATION_DELIVERY_EVIDENCE,
    OBLIGATION_DONE_MERGE_EVIDENCE,
)
from yoke_core.domain.gate_satisfier_resolution import missing_done_evidence_rungs
from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_evidence,
)

FLOW = "acme-hosted-production-release"
FIRST_MERGE = "b" * 40
SECOND_MERGE = "c" * 40


def _environment_id(conn, *, project_id: int) -> int:
    """Any environment of this project, created when the fixture has none."""
    row = conn.execute(
        "SELECT id FROM environments WHERE project_id = %s ORDER BY id LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is not None:
        return int(row[0])
    site = conn.execute(
        "SELECT id FROM sites WHERE project_id = %s ORDER BY id LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO environments (site, project_id, name, created_at) "
        "VALUES (%s, %s, 'prod', %s)",
        (int(site[0]), project_id, "2026-01-01T00:00:00Z"),
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id = %s "
            "ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()[0]
    )


def _item_delivering_through_a_release(conn, *, item_id: int) -> None:
    """A dash item whose close-out already pinned it to a persistent flow."""
    insert_item(conn, id=item_id, workflow_id="dash", status="release")
    project_id = int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )
    # A persistent tier is only declarable against a real environment; the
    # table constrains the pair.
    environment_id = _environment_id(conn, project_id=project_id)
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, name, status, "
        "stages, target_tier, target_environment_id, created_at) VALUES "
        "(%s, %s, %s, 'active', %s, 'persistent', %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        (
            FLOW,
            project_id,
            "Hosted production release",
            json.dumps([]),
            environment_id,
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.execute(
        "UPDATE items SET deployment_flow = %s WHERE id = %s", (FLOW, item_id)
    )
    conn.commit()


def _record(item_id: int, merge_sha: str):
    return handle_dash_evidence(
        FunctionCallRequest(
            function="direct_workflow.dash.evidence",
            actor=ActorContext(actor_id="2", session_id="close-out"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={
                "result_summary": "Landed the standalone change.",
                "verification_summary": "Registered verification passed.",
                "verification_status": "passed",
                "commit_sha": "a" * 40,
                "merge_sha": merge_sha,
                "touched_files": ["src/close_out.py"],
                "tree_root": "/repo/.worktrees/close-out",
                "tree_head_sha": "a" * 40,
            },
        )
    )


def _stamped(conn, item_id: int) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT obligation, rung_id FROM item_gate_satisfactions "
            "WHERE item_id = %s",
            (item_id,),
        ).fetchall()
    }


def test_a_second_landing_records_evidence_for_its_own_merge(
    test_db, monkeypatch
) -> None:
    item_id = 27410
    _item_delivering_through_a_release(test_db, item_id=item_id)
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))

    assert _record(item_id, FIRST_MERGE).primary_success is True
    second = _record(item_id, SECOND_MERGE)

    assert second.primary_success is True
    assert second.result_payload["evidence"]["merge_sha"] == SECOND_MERGE


def test_the_delivery_obligation_stays_owed_at_the_done_gate(
    test_db, monkeypatch
) -> None:
    """Merge evidence is recorded; the release still has to happen."""
    item_id = 27411
    _item_delivering_through_a_release(test_db, item_id=item_id)
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))

    assert _record(item_id, FIRST_MERGE).primary_success is True

    stamped = _stamped(test_db, item_id)
    assert OBLIGATION_DONE_MERGE_EVIDENCE in stamped
    assert OBLIGATION_DELIVERY_EVIDENCE not in stamped
    assert OBLIGATION_DELIVERY_EVIDENCE in missing_done_evidence_rungs(
        test_db, item_id=item_id, merge_recorded=True, agent_attested=False
    )
