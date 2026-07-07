"""Handler tests for readiness and path-claim flow function ids."""

from __future__ import annotations

from contextlib import contextmanager

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import claims_path_activation as cpa
from yoke_core.domain.handlers import readiness


def _item_request(function: str, payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="42", session_id="session-1"),
        target=TargetRef(kind="item", item_id=1800),
        payload=payload or {},
    )


def test_readiness_check_returns_classified_payload(monkeypatch) -> None:
    issue = {
        "code": "STALE_LINE_COUNT",
        "message": "stale",
        "remediation": "refresh",
        "context": {"path": "x.py", "recorded": 1, "actual": 2},
    }
    monkeypatch.setattr(
        readiness,
        "_run_readiness",
        lambda item_id: ("block", [issue], [{"message": "advisory"}]),
    )

    outcome = readiness.handle_check(_item_request("readiness.check.run"))

    assert outcome.primary_success is True
    assert outcome.result_payload["verdict"] == "block"
    assert outcome.result_payload["classification"] == "pure_stale_count"
    assert outcome.result_payload["issues"] == [issue]
    assert outcome.result_payload["advisories"] == [{"message": "advisory"}]


def test_readiness_check_missing_tool_returns_structured_error(monkeypatch) -> None:
    def missing_tool(_item_id: int):
        raise FileNotFoundError("git")

    monkeypatch.setattr(readiness, "_run_readiness", missing_tool)

    outcome = readiness.handle_check(_item_request("readiness.check.run"))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "readiness_prerequisite_missing"
    assert "git" in outcome.error.message


def test_repair_stale_count_calls_domain_repair(monkeypatch) -> None:
    issue = {
        "code": "STALE_LINE_COUNT",
        "message": "stale",
        "remediation": "refresh",
        "context": {"path": "x.py", "recorded": 1, "actual": 2},
    }
    monkeypatch.setattr(
        readiness,
        "_run_readiness",
        lambda item_id: ("block", [issue], []),
    )

    class Outcome:
        def to_payload(self):
            return {
                "success": True,
                "classification": "pure_stale_count",
                "item_id": 1800,
                "rerun_verdict": "pass",
            }

    from yoke_core.domain import idea_readiness_repair as repair_mod

    monkeypatch.setattr(
        repair_mod,
        "attempt_stale_count_repair",
        lambda *, item_id, issues: Outcome(),
    )

    outcome = readiness.handle_repair_stale_count(
        _item_request("readiness.repair_stale_count")
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["success"] is True
    assert outcome.result_payload["rerun_verdict"] == "pass"


def test_required_gate_handler_evaluates_target_item(monkeypatch) -> None:
    @contextmanager
    def fake_conn():
        yield object()

    from yoke_core.domain import path_claim_required_gate as gate_mod

    monkeypatch.setattr(cpa, "_connect_rw", fake_conn)
    monkeypatch.setattr(
        gate_mod,
        "evaluate",
        lambda conn, item_id: {
            "verdict": "pass",
            "reason": f"YOK-{item_id} covered",
            "satisfying_claims": [7],
        },
    )

    outcome = cpa.handle_required_gate(
        _item_request("claims.path.required_gate")
    )

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "verdict": "pass",
        "reason": "YOK-1800 covered",
        "satisfying_claims": [7],
    }


def test_activation_handler_uses_bound_actor_and_target(monkeypatch) -> None:
    @contextmanager
    def fake_conn():
        yield object()

    from yoke_core.domain import advance_path_claim_activation as activation_mod
    from yoke_core.domain.advance_path_claim_activation import (
        ActivationOutcome,
        ActivationResult,
    )

    calls = []

    def fake_run(conn, *, item_id, actor_id, session_id):
        calls.append((item_id, actor_id, session_id))
        return ActivationResult(
            item_id=item_id,
            actor_id=actor_id,
            outcomes=[
                ActivationOutcome(
                    claim_id=9,
                    state_before="planned",
                    state_after="active",
                )
            ],
        )

    monkeypatch.setattr(cpa, "_connect_rw", fake_conn)
    monkeypatch.setattr(activation_mod, "run_activation_phase", fake_run)

    outcome = cpa.handle_activation_run(
        _item_request("claims.path.activation_run")
    )

    assert outcome.primary_success is True
    assert calls == [(1800, 42, "session-1")]
    assert outcome.result_payload["actor_id"] == 42
    assert outcome.result_payload["outcomes"][0]["claim_id"] == 9
