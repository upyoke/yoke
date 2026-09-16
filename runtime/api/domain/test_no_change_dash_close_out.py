"""A no-change Dash closes reviewing → done without fabricated SHA, CI, or deploy."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain import (
    backlog_architecture_gate_runner,
    backlog_authoritative_status_gate,
    backlog_db_mutation_gate_runner,
    backlog_update_op,
    conflict_survey_gate,
    dash_evidence_gate,
    dash_posture_gate,
    db_helpers,
    deployment_flow_clearance as clearance,
    path_claims_gate_boundary,
    qa_gate_preconditions,
    qa_gates,
)
from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_evidence,
    handle_dash_survey,
)
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_release_status import close_out_route
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_workflow_binding_validation import (
    optional_unattached_qa_permits_empty,
)

ITEM_ID = 7110
SESSION_ID = "no-change-close"


class _NonClosingConnection:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        return None

    def __enter__(self):
        return self._connection

    def __exit__(self, *_exc):
        return None


@contextmanager
def _use_connection(connection):
    yield connection


def _bind_fixture_db(monkeypatch, test_db) -> None:
    def _connect(_path=None):
        return _NonClosingConnection(test_db)

    for module in (
        db_helpers,
        backlog_update_op,
        backlog_authoritative_status_gate,
        backlog_architecture_gate_runner,
        backlog_db_mutation_gate_runner,
        dash_evidence_gate,
        dash_posture_gate,
        path_claims_gate_boundary,
        qa_gate_preconditions,
        qa_gates,
        conflict_survey_gate,
    ):
        if hasattr(module, "connect"):
            monkeypatch.setattr(module, "connect", _connect)


def _request(
    function: str,
    payload: dict,
    *,
    actor_id: str,
    item_id: int = ITEM_ID,
    session_id: str = SESSION_ID,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=actor_id, session_id=session_id),
        target=TargetRef(kind="item", item_id=item_id, project_id="yoke"),
        payload=payload,
    )


def _empty_delivery_reads(monkeypatch) -> None:
    def _dispatch(*, function_id, **_kwargs):
        if function_id == "workflows.mechanics.get":
            return SimpleNamespace(
                success=True, result={"delivery_defaults": []}, error=None
            )
        if function_id == "done_transition.registered_flow_ids":
            return SimpleNamespace(success=True, result={"flow_ids": []}, error=None)
        raise AssertionError(function_id)

    monkeypatch.setattr(clearance, "call_dispatcher", _dispatch)


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
    assert dash_evidence_gate.evaluate(
        item_id=ITEM_ID, target_status="done", db_path="unused"
    ) is None
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


def test_sanctioned_close_out_sets_nonce_from_merge_only_delivery(
    test_db, monkeypatch,
):
    """The merge close-out command, not the test, asserts the done nonce."""
    item_id = 7111
    session_id = "no-change-cmd"
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
        id=item_id,
        workflow_id="dash",
        status="reviewing-implementation",
        title="No change command close-out",
    )
    insert_session(test_db, session_id)
    insert_item_claim(test_db, session_id, item_id)
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
            item_id=item_id,
            session_id=session_id,
        )
    )
    assert recorded.primary_success is True
    runtime = load_item_workflow_runtime(test_db, item_id)
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge_release_status.pinned_workflow_for_item",
        lambda _item: (runtime, ""),
    )
    item = {
        "id": item_id,
        "status": "reviewing-implementation",
        "deployment_flow": "",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
    }
    route = close_out_route(item, "reviewing-implementation")
    assert route.error == ""
    assert route.delivery_discharged is True
    assert "done" in route.stages
    nonces: list[tuple[str, bool]] = []

    def _dispatch(*, function_id, target=None, payload=None, **_kwargs):
        if function_id != "lifecycle.transition.execute":
            raise AssertionError(function_id)
        nonces.append(
            (str(payload["target_status"]), bool(payload.get("done_nonce_verified")))
        )
        outcome = handle_transition(
            FunctionCallRequest(
                function=function_id,
                actor=ActorContext(actor_id=actor_id, session_id=session_id),
                target=target,
                payload=payload,
            )
        )
        return FunctionCallResponse(
            success=outcome.primary_success,
            function=function_id,
            version="v1",
            result=outcome.result_payload or {},
            error=outcome.error,
        )

    monkeypatch.setattr(terminal, "call_dispatcher", _dispatch)
    monkeypatch.setattr(terminal.recovery, "claim_error", lambda *_a, **_k: "")
    status, error = terminal.transition_to_done(
        item_id=item_id,
        source_status="reviewing-implementation",
        repo_root="/tmp/no-change-repo",
        lane=LandedLane(branch="", target="main", commit_sha="", merge_sha=""),
        session_id=session_id,
        stages=route.stages,
        delivery_discharged=route.delivery_discharged,
    )
    assert error == ""
    assert status == "done"
    assert nonces[-1] == ("done", True)
    assert all(nonce is False for target, nonce in nonces if target != "done")
    row = test_db.execute(
        "SELECT status, merged_at FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    assert row[0] == "done"
    assert not row[1]
