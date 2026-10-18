"""Path-claim and level posture amendments accept holders or covering steering."""

from __future__ import annotations

from dataclasses import replace
import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import yoke_function_dispatch_claims as claims
from yoke_core.domain.yoke_function_registry import lookup
from yoke_core.domain.handlers.__init_register__ import register_all_handlers


@pytest.mark.parametrize(
    "holder,seat,key,allowed",
    [
        ("caller", False, "path_claims", True),
        ("other", True, "path_claims", True),
        ("other", False, "path_claims", False),
        ("", False, "path_claims", False),
        ("caller", False, "level", True),
        ("other", True, "level", True),
        ("other", False, "level", False),
        ("", True, "level", True),
        ("", False, "level", False),
        ("other", True, "verification", False),
        ("other", True, "merge_candidate_review", False),
    ],
)
def test_steering_amendable_posture_authority(monkeypatch, holder, seat, key, allowed):
    register_all_handlers()
    entry = lookup("workflows.item_posture.amend")
    request = FunctionCallRequest(
        function=entry.function_id,
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="item", item_id=42),
        payload={"key": key, "clear": True, "reason": "mistaken selection"},
    )
    monkeypatch.setattr(
        claims,
        "who_claims_for_item",
        lambda _: {"id": 5, "session_id": holder} if holder else None,
    )
    monkeypatch.setattr(
        claims,
        "steering_seat_for_request",
        lambda *_: ({"claim_id": 8}, "project") if seat else (None, "project"),
    )
    monkeypatch.setattr(claims, "_claim_recovery_item_ref", lambda _: "APP-7")
    evidence = {}
    response = claims.verify_claim(entry, request, evidence=evidence)
    assert (response is None) is allowed
    if allowed:
        assert evidence["authority"] == (
            "work_claim" if holder == "caller" else "steering"
        )
    else:
        assert response.error.code == "claim_required"


def test_steering_exception_does_not_authorize_other_item_writes(monkeypatch):
    register_all_handlers()
    entry = replace(
        lookup("workflows.item_posture.amend"), function_id="items.scalar.update"
    )
    request = FunctionCallRequest(
        function=entry.function_id,
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="item", item_id=42),
        payload={"key": "path_claims"},
    )
    monkeypatch.setattr(claims, "who_claims_for_item", lambda _: None)
    monkeypatch.setattr(claims, "_claim_recovery_item_ref", lambda _: "APP-7")
    monkeypatch.setattr(
        claims,
        "steering_seat_for_request",
        lambda *_: pytest.fail("unrelated write must not inspect steering"),
    )
    assert claims.verify_claim(entry, request).error.code == "claim_required"
