"""Handler coverage for the readiness observation handoff.

A readiness host without the item project's checkout publishes what its
file-reading checks needed; a caller that has the tree answers with what
they found. These cover both directions across the check and both repair
functions — the payloads only, with the checks themselves stubbed.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import readiness

from runtime.api.domain.handlers.test_readiness_handlers import (
    _UNPERFORMED_CHECK,
    _readiness_payload,
)


def _item_request(function: str, payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="42", session_id="session-1"),
        target=TargetRef(kind="item", item_id=1800),
        payload=payload or {},
    )


_LOCAL_REQUEST = {
    "item_id": 1800,
    "item_ref": "YOK-1800",
    "project_id": 7,
    "spec_sha256": "abc",
    "spec_text": "spec",
    "checks": ["verify_function_owners"],
}


def test_unperformed_check_publishes_what_a_host_with_files_would_need(
    monkeypatch,
) -> None:
    """The answer carries the request, so the caller can run the checks."""
    monkeypatch.setattr(
        readiness,
        "_run_readiness",
        lambda item_id, observations=None: _readiness_payload(
            "unavailable",
            "unavailable",
            unavailable=[_UNPERFORMED_CHECK],
            local_execution_request=_LOCAL_REQUEST,
        ),
    )

    outcome = readiness.handle_check(_item_request("readiness.check.run"))

    assert outcome.result_payload["local_execution_request"] == _LOCAL_REQUEST


def test_check_forwards_caller_observations_to_the_checks(monkeypatch) -> None:
    seen: list = []

    def record(item_id, observations=None):
        seen.append(observations)
        return _readiness_payload("pass", "pass")

    monkeypatch.setattr(readiness, "_run_readiness", record)
    observations = {"spec_sha256": "abc", "issues": []}

    outcome = readiness.handle_check(
        _item_request("readiness.check.run", {"local_observations": observations})
    )

    assert seen == [observations]
    assert outcome.result_payload["verdict"] == "pass"


def test_repair_refusal_carries_the_request_that_unblocks_it(monkeypatch) -> None:
    """A refused repair names the handoff, not just the missing checkout."""
    monkeypatch.setattr(
        readiness,
        "_run_readiness",
        lambda item_id, observations=None: _readiness_payload(
            "unavailable",
            "unavailable",
            unavailable=[_UNPERFORMED_CHECK],
            local_execution_request=_LOCAL_REQUEST,
        ),
    )

    for function, handler in (
        ("readiness.repair_stale_count", readiness.handle_repair_stale_count),
        ("readiness.repair_claim_coverage", readiness.handle_repair_claim_coverage),
    ):
        outcome = handler(_item_request(function))

        assert outcome.result_payload["success"] is False
        assert outcome.result_payload["local_execution_request"] == _LOCAL_REQUEST


def test_repairs_forward_caller_observations(monkeypatch) -> None:
    seen: list = []

    def record(item_id, observations=None):
        seen.append(observations)
        return _readiness_payload("pass", "pass")

    monkeypatch.setattr(readiness, "_run_readiness", record)
    observations = {"spec_sha256": "abc", "issues": []}

    for function, handler in (
        ("readiness.repair_stale_count", readiness.handle_repair_stale_count),
        ("readiness.repair_claim_coverage", readiness.handle_repair_claim_coverage),
    ):
        handler(_item_request(function, {"local_observations": observations}))

    assert seen == [observations, observations]
