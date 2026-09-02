"""Dash close-out persists the satisfier rungs that let it reach done."""

from __future__ import annotations

from contextlib import nullcontext

from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog, backlog_update_op, db_helpers
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    DELIVERY_EVIDENCE_LADDER,
    DONE_MERGE_EVIDENCE_LADDER,
    OBLIGATION_DELIVERY_EVIDENCE,
    OBLIGATION_DONE_MERGE_EVIDENCE,
    RUNG_AGENT_ATTESTED,
)
from yoke_core.domain.gate_satisfier_stamp import EVENT_STAMPED
from yoke_core.domain.handlers import gate_satisfier_rung
from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_evidence,
)


def test_dash_done_keeps_rung_rows_events_and_converged_facts(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    item_id = 27310
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        status="reviewing-implementation",
    )
    project_id = int(
        test_db.execute(
            "SELECT project_id FROM items WHERE id = %s",
            (item_id,),
        ).fetchone()[0]
    )
    test_db.execute(
        "DELETE FROM project_derived_facts WHERE project_id = %s",
        (project_id,),
    )
    test_db.commit()

    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: nullcontext(test_db),
    )
    outcome = handle_dash_evidence(
        FunctionCallRequest(
            function="direct_workflow.dash.evidence",
            actor=ActorContext(actor_id="2", session_id="dash-close-out"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={
                "result_summary": "Landed the standalone change.",
                "verification_summary": "Registered verification passed.",
                "verification_status": "passed",
                "commit_sha": "a" * 40,
                "merge_sha": "b" * 40,
                "touched_files": ["src/close_out.py"],
                "tree_root": "/repo/.worktrees/close-out",
                "tree_head_sha": "a" * 40,
            },
        )
    )
    assert outcome.primary_success is True

    rows = {
        str(row[0]): str(row[1])
        for row in test_db.execute(
            "SELECT obligation, rung_id FROM item_gate_satisfactions "
            "WHERE item_id = %s",
            (item_id,),
        ).fetchall()
    }
    assert set(rows) == {
        OBLIGATION_DONE_MERGE_EVIDENCE,
        OBLIGATION_DELIVERY_EVIDENCE,
    }
    assert rows[OBLIGATION_DONE_MERGE_EVIDENCE] in {
        rung.rung_id
        for rung in DONE_MERGE_EVIDENCE_LADDER.rungs
        if rung.rung_id != RUNG_AGENT_ATTESTED
    }
    assert rows[OBLIGATION_DELIVERY_EVIDENCE] in {
        rung.rung_id for rung in DELIVERY_EVIDENCE_LADDER.rungs
    }
    assert (
        int(
            test_db.execute(
                "SELECT COUNT(*) FROM project_derived_facts WHERE project_id = %s",
                (project_id,),
            ).fetchone()[0]
        )
        > 0
    )

    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lambda **_kwargs: None,
    )
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="done",
        done_nonce_verified=True,
        force=True,
        qa_bypass=True,
        no_github=True,
        rebuild_board=False,
    )

    assert result["success"] is True
    assert (
        test_db.execute(
            "SELECT status FROM items WHERE id = %s",
            (item_id,),
        ).fetchone()[0]
        == "done"
    )
    assert (
        int(
            test_db.execute(
                "SELECT COUNT(*) FROM item_gate_satisfactions WHERE item_id = %s",
                (item_id,),
            ).fetchone()[0]
        )
        == 2
    )
    assert (
        int(
            test_db.execute(
                "SELECT COUNT(*) FROM events WHERE event_name = %s AND item_id = %s",
                (EVENT_STAMPED, str(item_id)),
            ).fetchone()[0]
        )
        == 2
    )


def test_registered_rung_resolver_uses_the_shared_server_path(
    test_db,
    monkeypatch,
) -> None:
    item_id = 27311
    insert_item(test_db, id=item_id, workflow_id="dash")
    monkeypatch.setattr(
        gate_satisfier_rung,
        "_connect_rw",
        lambda: nullcontext(test_db),
    )

    outcome = gate_satisfier_rung.handle_resolve(
        FunctionCallRequest(
            function="gate_satisfier.rung.resolve",
            actor=ActorContext(actor_id="2", session_id="rung-resolver"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={
                "obligation": OBLIGATION_DONE_MERGE_EVIDENCE,
                "target_status": "done",
                "observed": {
                    "observed:merge_recorded": {
                        "present": True,
                        "detail": "fixture merge landed",
                    },
                    "observed:no_implementation_branch": {
                        "present": False,
                        "detail": "fixture branch existed",
                    },
                },
            },
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["satisfied"] is True
    assert outcome.result_payload["stamp_recorded"] is True
    assert (
        int(
            test_db.execute(
                "SELECT COUNT(*) FROM events WHERE event_name = %s AND item_id = %s",
                (EVENT_STAMPED, str(item_id)),
            ).fetchone()[0]
        )
        == 1
    )
