"""A no-change merge close-out supplies its terminal transition nonce."""


def test_sanctioned_close_out_sets_nonce_from_merge_only_delivery(
    test_db,
    monkeypatch,
):
    """The merge close-out command, not the test, asserts the done nonce."""
    import json

    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        FunctionCallResponse,
    )

    from yoke_core.domain.item_ref_resolution import resolve_item_ref

    from yoke_core.domain import standalone_item_merge_terminal as terminal

    from yoke_core.domain.handlers.lifecycle_transition import handle_transition

    from yoke_core.domain.handlers.direct_workflow_execution import handle_dash_evidence

    from yoke_core.domain.standalone_item_merge_landed import LandedLane

    from yoke_core.domain.standalone_item_merge_release_status import close_out_route

    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    from runtime.api.fixtures.backlog_inserts import insert_item

    from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session

    from runtime.api.domain.test_status_transition_preflight import (
        _isolate_status_effects,
    )

    from runtime.api.domain.test_no_change_dash_close_out import (
        _bind_fixture_db,
        _empty_delivery_reads,
        _request,
    )

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
    monkeypatch.setattr(
        terminal.evidence,
        "recorded",
        lambda _id: json.loads(
            test_db.execute(
                "SELECT content FROM item_sections WHERE item_id = %s "
                "AND section_name = 'Execution Evidence'",
                (item_id,),
            ).fetchone()[0]
        ),
    )
    nonces: list[tuple[str, bool]] = []

    def _dispatch(*, function_id, target=None, payload=None, **_kwargs):
        if function_id != "lifecycle.transition.execute":
            raise AssertionError(function_id)
        target = target.model_copy(
            update={"item_id": resolve_item_ref(test_db, target.public_ref)}
        )
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
