"""A recovered merge close-out finishes the release that owed its member."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def test_recovered_merge_close_out_finishes_settling_run(
    test_db: Any, monkeypatch
) -> None:
    from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_B
    from runtime.api.domain.test_deployment_run_auto_completion import _run_status
    from runtime.api.domain.test_independent_member_delivery_close_out import (
        MEMBER_A,
        MEMBER_B,
        _seed_final_run,
        _settle,
        _status,
    )
    from runtime.api.domain.test_status_transition_preflight import (
        _isolate_status_effects,
    )
    from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest
    from yoke_core.domain import (
        delivery_member_close_steps,
        standalone_item_merge_terminal,
    )
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.item_ref_resolution import resolve_item_ref
    from yoke_core.domain.handlers.lifecycle_transition import handle_transition
    from yoke_core.domain.standalone_item_merge_landed import LandedLane

    _isolate_status_effects(monkeypatch)
    run_id = "run-recovered-merge-close-out"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "done"

    prepare = delivery_member_close_steps.prepare_member_close

    def refuse_member(conn, *, item_id, public_ref):
        if item_id == MEMBER_B:
            return "member close-out prerequisite is temporarily unavailable"
        return prepare(conn, item_id=item_id, public_ref=public_ref)

    monkeypatch.setattr(
        delivery_member_close_steps, "prepare_member_close", refuse_member
    )
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='complete' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    refusal = cmd_update(run_id, "status", "succeeded")
    assert refusal and "temporarily unavailable" in refusal
    assert _status(test_db, MEMBER_B) == "release"
    assert _run_status(test_db, run_id) == "executing"
    assert test_db.execute(
        "SELECT settling_at FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()["settling_at"]

    monkeypatch.setattr(delivery_member_close_steps, "prepare_member_close", prepare)
    assert prepare(test_db, item_id=MEMBER_B, public_ref="member") == ""

    def dispatch(*, function_id, target, payload):
        target = target.model_copy(
            update={"item_id": resolve_item_ref(test_db, target.public_ref)}
        )
        outcome = handle_transition(
            FunctionCallRequest(
                function=function_id,
                actor=ActorContext(actor_id="2", session_id=HOLDER_B),
                target=target,
                payload=payload,
            )
        )
        return SimpleNamespace(success=outcome.primary_success, error=outcome.error)

    monkeypatch.setattr(standalone_item_merge_terminal, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        standalone_item_merge_terminal.git, "is_landed", lambda *_args: True
    )
    monkeypatch.setattr(
        standalone_item_merge_terminal.recovery, "claim_error", lambda *_args: ""
    )
    reached, error = standalone_item_merge_terminal.transition_to_done(
        item_id=render_item_ref(test_db, MEMBER_B),
        source_status="release",
        repo_root="/repo",
        lane=LandedLane(
            branch="member",
            target="main",
            commit_sha="a" * 40,
            merge_sha="b" * 40,
            touched_files=("src/member.py",),
            source="recorded landing",
        ),
        session_id=HOLDER_B,
        delivery_discharged=True,
    )

    assert error == ""
    assert reached == "done"
    assert _status(test_db, MEMBER_B) == "done"
    assert _run_status(test_db, run_id) == "succeeded"
