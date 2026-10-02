"""A credential-free local landing completes the item's real close-out path."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.standalone_merge_simulation_support import (
    git,
    stub_candidate_review,
)
from runtime.api.engines.local_merge_test_support import (
    make_local_checkout,
    assert_landed_clean,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import standalone_item_merge_cli as cli
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain import standalone_item_merge_close_out_transition as transition
from yoke_core.domain import merge_queue_route_selection as selection
from yoke_core.domain import dash_execution, project_identity
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.work_claim_targets import make_item_target


@pytest.mark.parametrize("layout", ["tracking-ref", "unfetched-remote", "no-remote"])
def test_local_merge_item_records_evidence_and_reaches_done(
    monkeypatch,
    tmp_path,
    test_db,
    layout,
    capsys,
):
    repo, lane, _ctx = make_local_checkout(monkeypatch, tmp_path, layout)
    source = git(lane, "rev-parse", "HEAD")
    item_id = 7
    session_id = "local-merge-test"
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        project="local-project",
        status="reviewing-implementation",
        architecture_impact="none",
    )
    ref = project_identity.render_item_ref(test_db, item_id)
    target = make_item_target(item_id)
    test_db.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, 'exclusive', %s, %s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    test_db.commit()
    item = {
        "id": item_id,
        "public_ref": ref,
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "local-project"},
        "worktrees": [{"branch": "finished", "path": str(lane), "commit_sha": source}],
    }
    monkeypatch.setattr(cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(cli, "_resolve_checkout", lambda *_a: (repo, "main"))
    monkeypatch.setattr(cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(cli.close_out.terminal.recovery, "claim_error", lambda *_a: "")
    monkeypatch.setattr(verify, "qa_preflight", lambda *_a, **_k: (source, ""))
    stub_candidate_review(monkeypatch)
    monkeypatch.setattr(
        selection, "project_declares_merge_queue", lambda *_a, **_k: (False, None)
    )
    monkeypatch.setattr(cli.merge_domain, "sync_item_to_github", lambda *_a: None)
    monkeypatch.setattr(
        cli.release_flow, "continue_prepared_release", lambda **_k: (None, "")
    )
    monkeypatch.setattr(
        transition,
        "close_out_route",
        lambda *_a, **_k: CloseOutRoute(
            stages=("release", "done"), delivery_discharged=True
        ),
    )
    monkeypatch.setattr(cli.pending, "clear_after_close_out", lambda *_a: "")
    monkeypatch.setattr(cli, "record_terminal_lane_close_out", lambda *_a, **_k: None)
    transitions = []

    def lifecycle_dispatch(*, function_id, payload, target, **_kwargs):
        assert function_id == "lifecycle.transition.execute"
        result = handle_transition(
            FunctionCallRequest(
                function=function_id,
                version="v1",
                target=target,
                payload=payload,
                actor={"actor_id": "op", "session_id": session_id},
            )
        )
        transitions.append(payload["target_status"])
        return SimpleNamespace(
            success=result.primary_success,
            result=result.result_payload,
            error=result.error,
        )

    def evidence_dispatch(*, function_id, payload, **_kwargs):
        assert function_id == "direct_workflow.dash.evidence"
        dash_execution.record_dash_evidence(test_db, item_id=item_id, **payload)
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(cli.close_out.terminal, "call_dispatcher", lifecycle_dispatch)
    monkeypatch.setattr(cli.evidence, "call_dispatcher", evidence_dispatch)
    assert (
        cli.run(
            [
                ref,
                "--session-id",
                session_id,
                "--result",
                "merged locally",
                "--verification",
                "credential-free Git ancestry and clean trees",
                "--json",
            ]
        )
        == 0
    )
    # Engine progress precedes the JSON envelope on stdout.
    stdout = capsys.readouterr().out
    envelope = json.loads(stdout[stdout.index('{\n  "already_merged"') :])
    assert envelope["status"] == "done"
    assert envelope["evidence_recorded"] is True
    assert envelope["published"] is False
    assert transitions == ["release", "done"]
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
            0
        ]
        == "done"
    )
    assert dash_execution.evaluate_dash_evidence(test_db, item_id).satisfied
    assert_landed_clean(repo, lane, source)
