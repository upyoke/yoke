"""A two-call queue landing retains its CI-backed Dash evidence."""

from __future__ import annotations

import json
from contextlib import nullcontext

from runtime.api.domain.handlers.capabilities_list_test_support import (
    insert_capability,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain import merge_queue_batch_receipt as batch_receipt
from yoke_core.domain import merge_queue_close_out as queue_close_out
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_evidence,
)
from yoke_core.domain.qa_command_plan_registration import (
    ensure_registered_command_plan,
)

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
COMBINED_SHA = "3" * 40


def test_no_posture_queue_handoff_stamps_ci_backed_merge(test_db, monkeypatch):
    """The queue receipt creates the only CI requirement this Dash needs."""
    _isolate_status_effects(monkeypatch)
    item_id = 9601
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        status="reviewing-implementation",
    )
    project_id = int(
        test_db.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,),
        ).fetchone()[0]
    )
    insert_capability(
        test_db,
        "ci_workflow_file",
        settings=json.dumps({"workflow_file": "yoke-ci.yml"}),
    )
    ensure_registered_command_plan(
        test_db,
        project_id=project_id,
        project="yoke",
        scope="full",
        command="python3 -m pytest",
    )
    test_db.commit()
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE item_id = %s", (item_id,),
    ).fetchone()[0] == 0

    receipt = batch_receipt.BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        members=("YOK-1",),
        head_sha=COMBINED_SHA,
        run_url="https://github.test/runs/42",
    )
    monkeypatch.setattr(queue_close_out, "stamp_merged_at", lambda _item: None)
    monkeypatch.setattr(
        queue_close_out,
        "observe_batch",
        lambda *_a, **_k: (receipt, None),
    )
    monkeypatch.setattr(
        queue_close_out,
        "read_pr_changed_files",
        lambda *_a, **_k: (("src/queue_close_out.py",), None),
    )
    monkeypatch.setattr(queue_close_out.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(
        queue_close_out, "fast_forward_main_checkout", lambda *_a, **_k: "",
    )

    close_out = landed.converge(
        item_id=item_id,
        project="yoke",
        public_ref="YOK-1",
        repo_root="",
        lane=landed.LandedLane(
            branch="YOK-1",
            target="main",
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("src/queue_close_out.py",),
            source="lane branch",
        ),
        queue_pr_number="42",
    )
    assert close_out.ok is True
    assert test_db.execute(
        "SELECT COUNT(*) FROM qa_runs r JOIN qa_requirements q "
        "ON q.id = r.qa_requirement_id WHERE q.item_id = %s "
        "AND r.performed_by = 'ci_run' AND r.verdict = 'pass'",
        (item_id,),
    ).fetchone()[0] == 1

    evidence = handle_dash_evidence(
        FunctionCallRequest(
            function="direct_workflow.dash.evidence",
            actor=ActorContext(actor_id="2", session_id="queue-close-out"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={
                "result_summary": "Landed through the merge queue.",
                "verification_summary": "The merge-group run passed.",
                "verification_status": "passed",
                "commit_sha": LANE_SHA,
                "merge_sha": MERGE_SHA,
                "touched_files": ["src/queue_close_out.py"],
                "tree_root": "/repo/.worktrees/queue-close-out",
                "tree_head_sha": LANE_SHA,
            },
        )
    )
    assert evidence.primary_success, evidence.error
    rung = test_db.execute(
        "SELECT rung_id FROM item_gate_satisfactions "
        "WHERE item_id = %s AND obligation = 'done_merge_evidence'",
        (item_id,),
    ).fetchone()
    assert rung[0] == "merged_with_ci"
