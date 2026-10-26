"""The last lease release names its freed cloud Test Machine on the response."""

from contextlib import nullcontext
from types import SimpleNamespace

from runtime.api.domain import test_agent_mission_cleanup as cleanup_support
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_qa_host_turns import KEY, MACHINE, _execution_wait, _notices
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain import test_machine_release_notice as notice
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.coordination_claims import acquire, release
from yoke_core.domain.handlers.claims_coordination_claim import handle_acquire_if_free
from yoke_core.domain.qa_host_turns import host_line
from yoke_core.domain.work_claim_targets import make_qa_admission_target

removed_mission = cleanup_support.removed_mission


def test_release_with_no_waiter_names_the_host(test_db):
    seed_qa_session(test_db, "owner")
    held = acquire(test_db, make_qa_admission_target(MACHINE), "owner")
    with notice.collect_released_hosts() as hosts:
        release(test_db, held.id, "complete")
    assert hosts == {MACHINE}


def test_release_to_a_queued_waiter_names_nothing(test_db, monkeypatch):
    seed_qa_session(test_db, "owner", "plan")
    _notices(monkeypatch)
    held = acquire(test_db, make_qa_admission_target(MACHINE), "owner")
    _execution_wait(test_db, "plan")
    with notice.collect_released_hosts() as hosts:
        release(test_db, held.id, "complete")
    assert hosts == set()


def test_acquire_if_free_refuses_without_joining_the_line(test_db, monkeypatch):
    seed_qa_session(test_db, "owner", "stopper")
    acquire(test_db, make_qa_admission_target(MACHINE), "owner")
    monkeypatch.setattr(
        "yoke_core.domain.handlers.claims_coordination_claim._connect_rw",
        lambda: nullcontext(test_db),
    )
    refused = handle_acquire_if_free(
        FunctionCallRequest(
            function="claims.coordination_claim.acquire_if_free",
            actor=ActorContext(actor_id="1", session_id="stopper"),
            target=TargetRef(kind="global"),
            payload={"project_id": "1", "key": KEY, "reason": "stop"},
        )
    )
    assert refused.error.code == "claim_held"
    assert host_line(test_db, MACHINE) == []


def test_mission_walk_end_release_names_the_host(removed_mission):
    request, _, original = removed_mission
    begun = handle_agent_mission_access(request)
    assert begun.primary_success, begun.error
    finish = {
        **request.payload,
        "cleanup": "finish",
        "lease_id": original["lease_id"],
        "restore": {"restored": True, "baseline": "fresh-host"},
    }
    with notice.collect_released_hosts() as hosts:
        finished = handle_agent_mission_access(
            request.model_copy(update={"payload": finish})
        )
    assert finished.primary_success, finished.error
    assert hosts == {original["settings"]["resource_name"]}


def _row(project, name, **settings):
    return SimpleNamespace(project=project, test_machine=name, settings=settings)


def test_only_hosts_with_an_instance_id_are_named(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_capability_rows.test_machine_capability_rows",
        lambda conn: [
            _row("yoke", "windows-lab", cloud_instance_id="i-1"),
            _row("yoke", "mac-lab"),
            _row("yoke", "other", cloud_instance_id="i-2"),
        ],
    )
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: nullcontext(None))
    assert notice.released_cloud_machines({"windows-lab", "mac-lab"}) == [
        {"project": "yoke", "test_machine": "windows-lab"}
    ]


def _response() -> FunctionCallResponse:
    return FunctionCallResponse(success=True, function="f", version="v1")


def test_response_names_freed_cloud_hosts(monkeypatch):
    machines = [{"project": "yoke", "test_machine": "windows-lab"}]
    monkeypatch.setattr(notice, "released_cloud_machines", lambda hosts: machines)
    response = notice.released_hosts_response(_response(), {"windows-lab"})
    assert response.released_test_machines == machines
    assert "released_test_machines" not in _response().model_dump()


def test_lookup_failure_warns_and_keeps_the_result(monkeypatch):
    def fail(hosts):
        raise RuntimeError("db down")

    monkeypatch.setattr(notice, "released_cloud_machines", fail)
    response = notice.released_hosts_response(_response(), {"windows-lab"})
    assert response.success and response.released_test_machines == []
    assert response.warnings[0].code == "test_machine_release_notice_failed"
