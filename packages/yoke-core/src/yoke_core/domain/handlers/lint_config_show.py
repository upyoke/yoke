"""``lint.config.show`` read handler: which lint-config governs this tree.

Read-only. The report shape, root-resolution reporting, and text
rendering live in :mod:`yoke_core.domain.lint_config_report`; this module
only validates the envelope and returns the payload.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class LintConfigShowRequest(BaseModel):
    root: Optional[str] = None


class LintConfigShowResponse(BaseModel):
    root: Optional[str]
    root_source: str
    root_env_var: Optional[str]
    config_path: Optional[str]
    config_exists: bool
    guards: List[Dict[str, Any]]
    text: str


def _error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_lint_config_show(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "lint.config.show requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    root = payload.get("root")
    if root is not None and not isinstance(root, str):
        return _error(
            "payload_invalid",
            "root must be a string when present",
            jsonpath="$.payload.root",
        )

    from yoke_core.domain import lint_config_report

    report = lint_config_report.build_report(root)
    result = report.as_dict()
    result["text"] = lint_config_report.render_text(report)
    return HandlerOutcome(result_payload=result, primary_success=True)
