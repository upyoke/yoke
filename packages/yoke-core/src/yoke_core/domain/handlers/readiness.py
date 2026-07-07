"""Function handlers for idea/refine readiness checks and repairs."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ReadinessCheckRequest(BaseModel):
    item_id: Optional[int] = None
    skip_readiness_check: bool = False


class ReadinessCheckResponse(BaseModel):
    verdict: str
    classification: str
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    advisories: List[Dict[str, Any]] = Field(default_factory=list)
    skip_reason: Optional[str] = None


class ReadinessRepairRequest(BaseModel):
    item_id: Optional[int] = None


class ReadinessRepairResponse(BaseModel):
    success: bool
    classification: str = ""
    item_id: int
    repaired_paths: List[Dict[str, Any]] = Field(default_factory=list)
    refused_paths: List[Dict[str, Any]] = Field(default_factory=list)
    field_written: str = ""
    rerun_verdict: str = ""
    rerun_issues: List[Dict[str, Any]] = Field(default_factory=list)
    error: str = ""
    audit_emitted: bool = False


class ReadinessPrdValidateRequest(BaseModel):
    item_id: Optional[int] = None
    strict: bool = False


class ReadinessPrdValidateResponse(BaseModel):
    item_id: int
    item_label: str
    strict: bool
    passed: bool
    pass_count: int
    warn_count: int
    fail_count: int
    passed_checks: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)
    report_text: str


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


def _issue_payload(issue: Any) -> Dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "remediation": issue.remediation,
        "context": issue.context,
    }


def _run_readiness(item_id: int) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    from yoke_core.domain import db_helpers
    from yoke_core.domain.idea_readiness_check import (
        run_all_advisories,
        run_all_checks,
    )

    conn = db_helpers.connect()
    try:
        issues = [_issue_payload(issue) for issue in run_all_checks(conn, item_id)]
        advisories = list(run_all_advisories(conn, item_id))
    finally:
        conn.close()
    return ("pass" if not issues else "block", issues, advisories)


def _check_payload(
    *, item_id: int, skip_readiness_check: bool = False,
) -> Dict[str, Any]:
    if skip_readiness_check:
        return {
            "verdict": "skipped",
            "classification": "pass",
            "issues": [],
            "advisories": [],
            "skip_reason": "operator-override",
        }
    from yoke_core.domain.idea_readiness_repair import (
        classify_readiness_issues,
    )

    verdict, issues, advisories = _run_readiness(item_id)
    return {
        "verdict": verdict,
        "classification": classify_readiness_issues(issues),
        "issues": issues,
        "advisories": advisories,
    }


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
        )
    except FileNotFoundError as exc:
        missing = getattr(exc, "filename", None) or str(exc)
        missing = missing or "required executable"
        return _err(
            "readiness_prerequisite_missing",
            "readiness.check.run could not find required executable "
            f"{missing!r}; install it or configure PATH on the Yoke API host "
            "before rerunning readiness.",
        )

    return HandlerOutcome(
        result_payload=payload,
        primary_success=True,
    )


def handle_prd_validate(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ReadinessPrdValidateRequest.model_validate(request.payload)
        item_id = _target_item_id(request, body.item_id)
    except Exception as exc:
        return _err(
            "payload_invalid",
            f"readiness.prd_validate.run payload invalid: {exc}",
        )

    from yoke_core.domain import prd_validate

    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            prd_body, item_label = prd_validate.resolve_body(
                f"YOK-{item_id}",
                None,
            )
    except SystemExit as exc:
        detail = stderr.getvalue().strip() or str(exc.code)
        return _err("prd_body_unavailable", detail)

    report = prd_validate.validate_prd(prd_body, item_label)
    passed = report.fail_count == 0 and (
        not body.strict or report.warn_count == 0
    )
    payload = ReadinessPrdValidateResponse(
        item_id=item_id,
        item_label=item_label,
        strict=body.strict,
        passed=passed,
        pass_count=report.pass_count,
        warn_count=report.warn_count,
        fail_count=report.fail_count,
        passed_checks=list(report.passed),
        warnings=list(report.warnings),
        failures=list(report.failures),
        report_text=_render_prd_report(item_label, report),
    ).model_dump()
    return HandlerOutcome(result_payload=payload, primary_success=passed)


def _render_prd_report(item_label: str, report: Any) -> str:
    from yoke_core.domain.prd_validate_render import print_report

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        print_report(item_label, report)
    return stdout.getvalue().rstrip()


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
        classify_readiness_issues,
    )

    verdict, issues, _advisories = _run_readiness(item_id)
    classification = classify_readiness_issues(issues)
    if verdict == "pass":
        payload = {
            "success": True,
            "classification": CLASS_PASS,
            "item_id": item_id,
            "rerun_verdict": "pass",
        }
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

    verdict, issues, _advisories = _run_readiness(item_id)
    if verdict == "pass":
        payload = {
            "success": True,
            "item_id": item_id,
            "rerun_verdict": "pass",
        }
    else:
        payload = attempt_claim_coverage_repair(
            item_id=item_id,
            issues=issues,
        ).to_payload()
    return HandlerOutcome(result_payload=payload, primary_success=True)


__all__ = [
    "ReadinessCheckRequest",
    "ReadinessCheckResponse",
    "ReadinessPrdValidateRequest",
    "ReadinessPrdValidateResponse",
    "ReadinessRepairRequest",
    "ReadinessRepairResponse",
    "handle_check",
    "handle_prd_validate",
    "handle_repair_claim_coverage",
    "handle_repair_stale_count",
]
