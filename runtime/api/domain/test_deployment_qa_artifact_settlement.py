"""A standalone verdict and its artifact settle only the accepting member."""

from uuid import uuid4

import pytest

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import HOLDER_A
from runtime.api.domain.independent_member_delivery_close_out_test_support import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _status,
)
from runtime.api.domain.run_success_member_settlement_test_support import _claim_held
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog import insert_qa_requirement, insert_qa_run
from runtime.api.fixtures.dispatch_actor import register_session_actor
from yoke_core.domain import machine_config
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.yoke_function_dispatch import dispatch

RUN = "run-late-case-artifact"
STAGE = "item-qa"


@pytest.fixture
def member_call(test_db, monkeypatch, tmp_path):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    _isolate_status_effects(monkeypatch)
    _seed_final_run(test_db, RUN, shared_qa=False)
    actor = register_session_actor(test_db, HOLDER_A)
    for member in (MEMBER_A, MEMBER_B):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )
    requirement = test_db.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND method_id='command'",
        (RUN, MEMBER_A),
    ).fetchone()["id"]
    test_db.commit()

    def call(function, payload, *, request_id=None):
        response = dispatch(
            {
                "function": function,
                "request_id": request_id or str(uuid4()),
                "actor": {"actor_id": str(actor), "session_id": HOLDER_A},
                "target": {"kind": "qa_requirement", "qa_requirement_id": requirement},
                "payload": payload,
            }
        )
        assert response.success, response.error
        return response

    return call


def _record_pass(call, *, request_id=None):
    return call(
        "qa.run.record_verdict",
        {"performed_by": "worktree_run", "verdict": "pass"},
        request_id=request_id,
    ).result["qa_run_id"]


def _attach_log_response(call, run_id, *, request_id=None):
    return call(
        "qa.artifact.add",
        {
            "run_id": run_id,
            "artifact_type": "log",
            "filename": "smoke.txt",
            "content_type": "text/plain",
            "content_base64": "cGFzc2VkCg==",
        },
        request_id=request_id,
    )


def _attach_log(call, run_id, *, request_id=None):
    response = _attach_log_response(call, run_id, request_id=request_id)
    assert not response.warnings, response.warnings
    return response.result["qa_artifact_id"]


def _assert_closed_independently(conn, run_id, artifact):
    assert _status(conn, MEMBER_A) == "done"
    assert not _claim_held(conn, MEMBER_A)
    assert _status(conn, MEMBER_B) == "release"
    assert _claim_held(conn, MEMBER_B)
    assert conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()[:] == ("executing", STAGE)
    assert (
        conn.execute("SELECT verdict FROM qa_runs WHERE id=%s", (run_id,)).fetchone()[0]
        == "pass"
    )
    assert (
        conn.execute(
            "SELECT id FROM qa_artifacts WHERE qa_run_id=%s", (run_id,)
        ).fetchall()[0][0]
        == artifact
    )


def test_late_artifact_closes_member_without_redriving_the_run(test_db, member_call):
    verdict_request, artifact_request = str(uuid4()), str(uuid4())
    run_id = _record_pass(member_call, request_id=verdict_request)
    assert _status(test_db, MEMBER_A) == "release"
    assert _claim_held(test_db, MEMBER_A)
    artifact = _attach_log(member_call, run_id, request_id=artifact_request)

    _assert_closed_independently(test_db, run_id, artifact)
    assert _record_pass(member_call, request_id=verdict_request) == run_id
    assert _attach_log(member_call, run_id, request_id=artifact_request) == artifact
    _assert_closed_independently(test_db, run_id, artifact)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id=%s", (run_id,)
        ).fetchone()[0]
        == 1
    )


def test_artifact_before_verdict_still_closes_member(test_db, member_call):
    run_id = member_call("qa.run.add", {"performed_by": "worktree_run"}).result[
        "qa_run_id"
    ]
    artifact = _attach_log(member_call, run_id)
    assert _status(test_db, MEMBER_A) == "release"
    assert _claim_held(test_db, MEMBER_A)

    member_call("qa.run.complete", {"run_id": run_id, "verdict": "pass"})
    _assert_closed_independently(test_db, run_id, artifact)


def test_late_artifact_survives_member_close_out_refusal(test_db, member_call):
    blocker = insert_qa_requirement(
        test_db, item_id=MEMBER_A, blocking_mode="non_blocking"
    )
    capture = insert_qa_run(
        test_db,
        qa_requirement_id=blocker["id"],
        verdict=None,
        execution_status="captured",
    )
    test_db.commit()
    run_id = _record_pass(member_call)
    artifact = _attach_log(member_call, run_id)

    assert _status(test_db, MEMBER_A) == "release"
    assert _claim_held(test_db, MEMBER_A)
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        == "pass"
    )
    assert (
        test_db.execute(
            "SELECT qa_run_id FROM qa_artifacts WHERE id=%s", (artifact,)
        ).fetchone()[0]
        == run_id
    )
    key = item_qa_accepted_idempotency_key(MEMBER_A, RUN) + ":blocked:%"
    [notice] = test_db.execute(
        "SELECT body FROM session_messages WHERE idempotency_key LIKE %s", (key,)
    ).fetchall()
    assert "Automatic close-out failed" in notice[0]
    assert f"run #{capture['id']}:" in notice[0]
    assert "yoke qa gate-summary" in notice[0]


def test_stage_settlement_refusal_returns_saved_artifact(
    test_db, member_call, monkeypatch
):
    run_id = _record_pass(member_call)

    def refused(*args, **kwargs):
        assert (
            test_db.execute(
                "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id=%s", (run_id,)
            ).fetchone()[0]
            == 1
        )
        raise ValueError(
            "qa_execution_owner_changed: ownership changed during settlement"
        )

    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_settlement.settle_subject", refused
    )
    response = _attach_log_response(member_call, run_id)

    artifact = response.result["qa_artifact_id"]
    [warning] = response.warnings
    assert warning.code == "qa_verdict_settlement_refused"
    assert "The artifact is recorded" in warning.detail
    assert "qa_execution_owner_changed" in warning.detail
    assert "watch deploy -- " + RUN in warning.detail
    assert _status(test_db, MEMBER_A) == "release"
    assert _claim_held(test_db, MEMBER_A)
    assert test_db.execute(
        "SELECT r.verdict,a.id FROM qa_runs r JOIN qa_artifacts a ON a.qa_run_id=r.id "
        "WHERE r.id=%s",
        (run_id,),
    ).fetchone()[:] == ("pass", artifact)
