"""Function handlers for idea/refine readiness checks and repairs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain.idea_readiness_results import VERDICT_UNAVAILABLE


class ReadinessCheckRequest(BaseModel):
    item_id: Optional[int] = None
    skip_readiness_check: bool = False
    local_observations: Optional[Dict[str, Any]] = None


class ReadinessCheckResponse(BaseModel):
    verdict: str
    classification: str
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    unavailable_checks: List[Dict[str, Any]] = Field(default_factory=list)
    advisories: List[Dict[str, Any]] = Field(default_factory=list)
    local_execution_request: Optional[Dict[str, Any]] = None
    skip_reason: Optional[str] = None


class ReadinessRepairRequest(BaseModel):
    item_id: Optional[int] = None
    local_observations: Optional[Dict[str, Any]] = None


class ReadinessRepairResponse(BaseModel):
    success: bool
    classification: str = ""
    item_id: int
    repaired_paths: List[Dict[str, Any]] = Field(default_factory=list)
    refused_paths: List[Dict[str, Any]] = Field(default_factory=list)
    unavailable_checks: List[Dict[str, Any]] = Field(default_factory=list)
    local_execution_request: Optional[Dict[str, Any]] = None
    field_written: str = ""
    rerun_verdict: str = ""
    rerun_issues: List[Dict[str, Any]] = Field(default_factory=list)
    error: str = ""
    audit_emitted: bool = False


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _target_item_id(request: FunctionCallRequest, payload_item_id: object) -> int:
    if payload_item_id is not None:
        return int(payload_item_id)
    if request.target.item_id is not None:
        return int(request.target.item_id)
    raise ValueError("readiness function requires a resolved item target")


def _unavailable_repair_payload(
    item_id: int, readiness: Dict[str, Any],
) -> Dict[str, Any]:
    """Refuse a repair the executing host cannot verify afterwards.

    Repair rewrites the item from what the checks read on disk, so a host
    with no checkout has nothing to repair against and no way to prove the
    rerun. The refusal carries the unperformed checks and their recovery,
    plus the ``local_execution_request`` a caller holding the checkout
    answers to turn this same call into a performed one.
    """
    return {
        "success": False,
        "classification": str(readiness["classification"]),
        "item_id": item_id,
        "rerun_verdict": str(readiness["verdict"]),
        "rerun_issues": list(readiness["issues"]),
        "unavailable_checks": list(readiness["unavailable_checks"]),
        "local_execution_request": readiness["local_execution_request"],
        "error": (
            "readiness validation was not performed on this host; repair "
            "needs the item project's checkout"
        ),
    }


def _run_readiness(
    item_id: int, local_observations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run every readiness check for one item and render its payload.

    ``unavailable_checks`` names the checks the executing host could not
    perform — each carries its own reason, supported recovery, and
    ``retryable`` flag. A non-empty list is never a pass.

    A host without the item project's checkout publishes what those
    checks need as ``local_execution_request``, so a caller that does
    have the tree can run them and hand back ``local_observations``.
    """
    from yoke_core.domain import db_helpers
    from yoke_core.domain.idea_readiness_check import run_all_checks
    from yoke_core.domain.idea_readiness_local_inputs import (
        build_local_execution_request,
        read_spec,
    )
    from yoke_core.domain.idea_readiness_checkout import (
        CHECKOUT_UNAVAILABLE_REASON,
    )

    conn = db_helpers.connect()
    try:
        outcome = run_all_checks(conn, item_id, local_observations)
        unavailable = outcome.unavailable_payloads()
        request = (
            build_local_execution_request(conn, item_id, read_spec(conn, item_id))
            if any(
                u["reason"] == CHECKOUT_UNAVAILABLE_REASON for u in unavailable
            )
            else None
        )
    finally:
        conn.close()
    return {
        "verdict": outcome.verdict,
        "classification": outcome.classification,
        "issues": outcome.issue_payloads(),
        "unavailable_checks": unavailable,
        "advisories": list(outcome.advisories),
        "local_execution_request": request,
    }


def _check_payload(
    *,
    item_id: int,
    skip_readiness_check: bool = False,
    local_observations: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if skip_readiness_check:
        return {
            "verdict": "skipped",
            "classification": "pass",
            "issues": [],
            "unavailable_checks": [],
            "advisories": [],
            "skip_reason": "operator-override",
        }
    return _run_readiness(item_id, local_observations)


def handle_check(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ReadinessCheckRequest.model_validate(request.payload)
        item_id = _target_item_id(request, body.item_id)
    except Exception as exc:
        return _err("payload_invalid", f"readiness.check.run payload invalid: {exc}")

    try:
        payload = _check_payload(
            item_id=item_id,
            skip_readiness_check=bool(body.skip_readiness_check),
            local_observations=body.local_observations,
        )
    except FileNotFoundError as exc:
        missing = getattr(exc, "filename", None) or str(exc)
        missing = missing or "required executable"
        return _err(
            "readiness_prerequisite_missing",
            "readiness.check.run could not find required executable "
            f"{missing!r}; install it or configure PATH on the Yoke API host "
            "before rerunning readiness. A missing project checkout is a "
            "different answer: it comes back as a successful result whose "
            "verdict is 'unavailable'.",
        )

    return HandlerOutcome(
        result_payload=payload,
        primary_success=True,
    )


def handle_repair_stale_count(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ReadinessRepairRequest.model_validate(request.payload)
        item_id = _target_item_id(request, body.item_id)
    except Exception as exc:
        return _err(
            "payload_invalid",
            f"readiness.repair_stale_count payload invalid: {exc}",
        )

    from yoke_core.domain.idea_readiness_repair import (
        CLASS_PASS,
        CLASS_PURE_STALE_COUNT,
        attempt_stale_count_repair,
    )

    readiness = _run_readiness(item_id, body.local_observations)
    verdict = str(readiness["verdict"])
    issues = list(readiness["issues"])
    classification = str(readiness["classification"])
    if verdict == "pass":
        payload = {
            "success": True,
            "classification": CLASS_PASS,
            "item_id": item_id,
            "rerun_verdict": "pass",
        }
    elif verdict == VERDICT_UNAVAILABLE:
        payload = _unavailable_repair_payload(item_id, readiness)
    elif classification != CLASS_PURE_STALE_COUNT:
        payload = {
            "success": False,
            "classification": classification,
            "item_id": item_id,
            "rerun_verdict": verdict,
            "rerun_issues": issues,
            "error": "only pure stale-count handled by this repair",
        }
    else:
        payload = attempt_stale_count_repair(
            item_id=item_id,
            issues=issues,
        ).to_payload()
    return HandlerOutcome(result_payload=payload, primary_success=True)


def handle_repair_claim_coverage(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ReadinessRepairRequest.model_validate(request.payload)
        item_id = _target_item_id(request, body.item_id)
    except Exception as exc:
        return _err(
            "payload_invalid",
            f"readiness.repair_claim_coverage payload invalid: {exc}",
        )

    from yoke_core.domain.idea_readiness_repair_claim_coverage import (
        attempt_claim_coverage_repair,
    )

    readiness = _run_readiness(item_id, body.local_observations)
    verdict = str(readiness["verdict"])
    if verdict == "pass":
        payload = {
            "success": True,
            "item_id": item_id,
            "rerun_verdict": "pass",
        }
    elif verdict == VERDICT_UNAVAILABLE:
        payload = _unavailable_repair_payload(item_id, readiness)
    else:
        payload = attempt_claim_coverage_repair(
            item_id=item_id,
            issues=list(readiness["issues"]),
        ).to_payload()
    return HandlerOutcome(result_payload=payload, primary_success=True)


__all__ = [
    "ReadinessCheckRequest",
    "ReadinessCheckResponse",
    "ReadinessRepairRequest",
    "ReadinessRepairResponse",
    "handle_check",
    "handle_repair_claim_coverage",
    "handle_repair_stale_count",
]
