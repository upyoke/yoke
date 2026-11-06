"""A no-change Dash closes reviewing → done without fabricated SHA, CI, or deploy."""

from __future__ import annotations

from runtime.api.domain.no_change_dash_close_out_test_support import (
    ITEM_ID as ITEM_ID,
    SESSION_ID as SESSION_ID,
    _NonClosingConnection as _NonClosingConnection,
    _bind_fixture_db as _bind_fixture_db,
    _empty_delivery_reads as _empty_delivery_reads,
    _request as _request,
)


from yoke_core.domain.handlers.lifecycle_transition import handle_transition


import json
from contextlib import contextmanager

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
from yoke_core.domain import (
    dash_evidence_gate,
    deployment_flow_clearance as clearance,
    qa_gates,
)
from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_evidence,
    handle_dash_survey,
)
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_workflow_binding_validation import (
    optional_unattached_qa_permits_empty,
)


@contextmanager
def _use_connection(connection):
    yield connection


def test_no_change_dash_closes_without_sha_ci_or_deploy(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    _bind_fixture_db(monkeypatch, test_db)
    _empty_delivery_reads(monkeypatch)
    actor_id = str(
        test_db.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )
    insert_item(
        test_db,
        id=ITEM_ID,
        workflow_id="dash",
        status="implementing",
        title="No change close-out",
    )
    insert_session(test_db, SESSION_ID)
    insert_item_claim(test_db, SESSION_ID, ITEM_ID)

    surveyed = handle_dash_survey(
        _request(
            "direct_workflow.dash.survey",
            {"paths": [], "path_sizes": [], "no_changes": True},
            actor_id=actor_id,
        )
    )
    assert surveyed.primary_success is True
    assert surveyed.result_payload["no_changes"] is True

    recorded = handle_dash_evidence(
        _request(
            "direct_workflow.dash.evidence",
            {
                "result_summary": "No code change was required.",
                "verification_summary": "Recorded no-changes; optional QA unattached.",
                "verification_status": "passed",
                "commit_sha": "",
                "merge_sha": "",
                "touched_files": [],
                "tree_root": "",
                "tree_head_sha": "",
                "no_changes": True,
            },
            actor_id=actor_id,
        )
    )
    assert recorded.primary_success is True
    evidence = recorded.result_payload["evidence"]
    assert evidence["no_changes"] is True
    assert evidence["commit_sha"] == ""
    assert evidence["merge_sha"] == ""
    assert evidence["touched_files"] == []
    assert (
        dash_evidence_gate.evaluate(
            item_id=ITEM_ID, target_status="done", db_path="unused"
        )
        is None
    )
    assert optional_unattached_qa_permits_empty(test_db, ITEM_ID) is True
    qa = qa_gates.check_verification_gate(
        GateTarget(item_id=ITEM_ID),
        "unused",
        transition_name="release",
    )
    assert qa.passed is True
    assert (
        clearance.resolve_delivery_clearance(
            deploy_flow="", item_project="yoke", workflow_id="dash"
        ).merge_only
        is True
    )

    for source, target, extra in (
        ("implementing", "reviewing-implementation", {}),
        ("reviewing-implementation", "release", {}),
        ("release", "done", {"done_nonce_verified": True}),
    ):
        outcome = handle_transition(
            _request(
                "lifecycle.transition.execute",
                {
                    "source_status": source,
                    "target_status": target,
                    "reason": f"no-change {source} to {target}",
                    **extra,
                },
                actor_id=actor_id,
            )
        )
        assert outcome.primary_success is True, outcome.error

    row = test_db.execute(
        "SELECT status, merged_at, deployment_flow FROM items WHERE id = %s",
        (ITEM_ID,),
    ).fetchone()
    assert row[0] == "done"
    assert not row[1]
    assert not row[2]
    runs = test_db.execute(
        "SELECT COUNT(*) FROM deployment_runs WHERE 1 = 1"
    ).fetchone()[0]
    assert int(runs) == 0
    stored = json.loads(
        test_db.execute(
            "SELECT content FROM item_sections WHERE item_id = %s "
            "AND section_name = 'Execution Evidence'",
            (ITEM_ID,),
        ).fetchone()[0]
    )
    assert stored["commit_sha"] == ""
    assert stored["merge_sha"] == ""
    assert stored["no_changes"] is True
