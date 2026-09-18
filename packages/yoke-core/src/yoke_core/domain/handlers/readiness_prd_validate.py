"""Function handler for the PRD structure validation report.

Shares the ``readiness.*`` function family with
:mod:`yoke_core.domain.handlers.readiness` but none of its machinery: a
PRD validation reads the rendered body and reports on its sections, and
never touches the item project's working tree.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


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


def handle_prd_validate(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.handlers.readiness import _target_item_id

    try:
        body = ReadinessPrdValidateRequest.model_validate(request.payload)
        item_id = _target_item_id(request, body.item_id)
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=f"readiness.prd_validate.run payload invalid: {exc}",
            ),
        )

    from yoke_core.domain import prd_validate

    from yoke_core.domain.project_identity_item_ref import item_ref_for_id

    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            prd_body, item_label = prd_validate.resolve_body(
                item_ref_for_id(int(item_id)),
                None,
            )
    except SystemExit as exc:
        detail = stderr.getvalue().strip() or str(exc.code)
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code="prd_body_unavailable", message=detail),
        )

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


__all__ = [
    "ReadinessPrdValidateRequest",
    "ReadinessPrdValidateResponse",
    "handle_prd_validate",
]
