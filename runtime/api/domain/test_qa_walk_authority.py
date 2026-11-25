from types import SimpleNamespace

import pytest

from yoke_core.domain import qa_walk_authority as authority
from yoke_core.domain.qa_plan_partition_chains import partition_key


ROSTER = [{"requirement_id": 44, "execution_target_digest": "target"}]
KEY = partition_key(ROSTER)
EXECUTION = {
    "id": "execution", "session_id": "walker", "item_id": 11,
    "transition_id": "reviewing", "roster": ROSTER,
}


def request(function, *, requirement=None, **payload):
    return SimpleNamespace(
        actor=SimpleNamespace(session_id="walker"),
        target=SimpleNamespace(qa_requirement_id=requirement),
        function=function, payload=payload,
    )


@pytest.fixture
def launch(monkeypatch):
    def registered(conn, *, item_id, session_id):
        if item_id == 11 and session_id == "walker":
            return authority.WalkLaunch("requester", "reviewing", KEY)
        return None

    monkeypatch.setattr(authority, "walk_launch", registered)
    monkeypatch.setattr(
        authority, "get_claim_for_work_unit",
        lambda conn, *, item_id: {"id": 17, "session_id": "requester"},
    )
    monkeypatch.setattr(authority, "select_plan_execution", lambda *_args, **_kwargs: EXECUTION)


def test_launch_is_exactly_one_partition_of_one_item(launch):
    begin = request("qa.plan_execution.begin", transition_id="reviewing", partition=KEY)
    assert authority.delegated_walk_grants(None, begin, item_id=11)
    assert not authority.delegated_walk_grants(None, begin, item_id=12)
    for change in ({"transition_id": "release"}, {"partition": "f" * 64}):
        other = request("qa.plan_execution.begin", **{**begin.payload, **change})
        with pytest.raises(authority.WalkAuthorityError, match="delegates one item part"):
            authority.delegated_walk_grants(None, other, item_id=11)


def test_only_owned_execution_functions_use_delegation_and_owner_can_abort(launch, monkeypatch):
    heartbeat = request("qa.plan_execution.heartbeat", execution_id="execution")
    assert authority.delegated_walk_grants(None, heartbeat, item_id=11)
    for function in (
        "qa.case.waive", "qa.run.record_verdict", "qa.plan_execution.adopt",
        "qa.plan_execution.reconcile",
    ):
        assert not authority.delegated_walk_grants(None, request(function), item_id=11)
    monkeypatch.setattr(authority, "_artifact_execution_id", lambda *_args, **_kwargs: "execution")
    for function in ("qa.artifact.add", "qa.artifact.presign"):
        assert authority.delegated_walk_grants(
            None, request(function, requirement=44, run_id=5), item_id=11,
        )
        assert not authority.delegated_walk_grants(
            None, request(function, requirement=45, run_id=6), item_id=11,
        )
    monkeypatch.setattr(authority, "get_claim_for_work_unit", lambda *_args, **_kwargs: None)
    with pytest.raises(authority.WalkDelegationLapsed):
        authority.delegated_walk_grants(None, heartbeat, item_id=11)
    assert authority.delegated_walk_grants(
        None, request("qa.plan_execution.abort", execution_id="execution"), item_id=11,
    )


def test_releasing_the_claim_between_dispatch_and_lock_refuses(launch, monkeypatch):
    begin = request("qa.plan_execution.begin", transition_id="reviewing", partition=KEY)
    assert authority.delegated_walk_grants(None, begin, item_id=11)
    monkeypatch.setattr(authority, "marker", lambda conn: "%s")
    monkeypatch.setattr(authority, "query_one", lambda *_args, **_kwargs: None)
    with pytest.raises(authority.WalkDelegationLapsed):
        authority.require_walk_claim(
            None, item_id=11, launch=authority.WalkLaunch("requester", "reviewing", KEY), lock=True,
        )
