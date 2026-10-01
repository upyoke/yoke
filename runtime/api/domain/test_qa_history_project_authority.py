"""QA evidence and host retirement retain authority after delivery ends."""

from unittest import mock

import pytest

from runtime.api.domain.deployment_member_qa_authorization_test_support import (
    RUN,
    STAGE,
    _consumer_actor,
    _entry,
    _mixed_run,
    _request,
)
from runtime.api.domain.test_coordination_claim_project_authority import (
    _project_owner,
    _qa_host_claim,
    _session,
    conn as authority_conn,
)
from runtime.api.fixtures.bound_source_release import CONSUMER_ITEM_ID
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
from yoke_core.domain.yoke_function_dispatch_qa_claims import qa_subject_claim_verdict
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


@pytest.fixture
def conn():
    yield from authority_conn.__wrapped__()


@pytest.mark.parametrize(
    "function", ["qa.requirement.get", "qa.artifact.add", "qa.artifact.presign"]
)
def test_detached_member_requirement_keeps_its_project(
    test_db, tmp_path, monkeypatch, function
):
    release = _mixed_run(test_db, tmp_path, monkeypatch)
    actor_id = _consumer_actor(test_db, release["consumer_id"])
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=CONSUMER_ITEM_ID,
        agent_plan="consumer-smoke",
    )
    requirement_id = int(result["created_requirement_ids"][0])
    test_db.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (RUN,))
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded', current_stage='complete' "
        "WHERE id=%s",
        (RUN,),
    )
    test_db.commit()
    request = _request(function, requirement_id=requirement_id, project=None)
    request.actor.actor_id = str(actor_id)
    permission = check_dispatch_permission(test_db, _entry(function), request)
    assert permission.error is None
    assert permission.project_id == release["consumer_id"]
    # Storage and dispatch agree; neither borrows the carrier's project.
    from yoke_core.domain.qa_artifact_owner import requirement_storage_owner

    assert requirement_storage_owner(test_db, requirement_id)["project_id"] == (
        permission.project_id
    )
    with mock.patch(
        "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
        return_value={"id": 17, "session_id": "consumer-qa"},
    ):
        assert qa_subject_claim_verdict(request)[0]
    # The carrier's owner cannot acquire authority over the consumer's evidence.
    request.actor.actor_id = str(
        _consumer_actor(test_db, resolve_project_id(test_db, "yoke"))
    )
    assert check_dispatch_permission(test_db, _entry(function), request).error
    request.actor.actor_id = str(actor_id)
    request.target.project_id = "yoke"
    assert check_dispatch_permission(test_db, _entry(function), request).error
    # This ownership lookup does not reopen a retired execution stage.
    stage_request = _request("qa.plan.materialize", member=release["consumer_ref"])
    stage_request.actor.actor_id = str(actor_id)
    assert check_dispatch_permission(
        test_db, _entry(stage_request.function), stage_request
    ).error


def test_qa_host_work_release_resolves_holder_and_keeps_self_only(conn):
    project_id = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, project_id)
    _session(conn, "holder-session", project_id)
    claim_id = _qa_host_claim(conn, machine="test-host", session_id="holder-session")
    request = FunctionCallRequest(
        function="claims.work.release",
        actor=ActorContext(actor_id=str(actor_id), session_id="holder-session"),
        target=TargetRef(kind="global", claim_id=claim_id),
        payload={"claim_id": claim_id, "reason": "completed"},
    )
    permission = check_dispatch_permission(conn, _entry(request.function), request)
    assert permission.error is None
    assert permission.project_id == project_id
    from types import SimpleNamespace

    entry = SimpleNamespace(
        claim_required_kind="self_only", function_id=request.function, version="v1"
    )
    with mock.patch(
        "yoke_core.domain.yoke_function_dispatch_claims._claim_row_for_id",
        return_value={"id": claim_id, "session_id": "holder-session"},
    ):
        assert verify_claim(entry, request) is None
        request.actor.session_id = "other-session"
        assert verify_claim(entry, request) is not None
    outsider = _project_owner(conn, resolve_project_id(conn, "externalwebapp"))
    request.actor.actor_id = str(outsider)
    assert check_dispatch_permission(conn, _entry(request.function), request).error
    request.actor.actor_id = str(actor_id)
    request.actor.session_id = "holder-session"
    from yoke_core.domain.handlers import claims_work

    from contextlib import nullcontext

    with mock.patch.object(claims_work, "_connect_rw", return_value=nullcontext(conn)):
        outcome = claims_work.handle_release(request)
    assert outcome.primary_success
    assert outcome.result_payload["released_at"]
    assert conn.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (claim_id,)
    ).fetchone()[0]
