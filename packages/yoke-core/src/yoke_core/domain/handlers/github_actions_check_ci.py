"""Handler for ``github_actions.check_ci`` — main-branch CI advisory check.

Reads the latest workflow run for ``(repo, workflow)`` on ``branch``
via :mod:`yoke_core.domain.gh_rest_transport`, classifies the result
into one of the canonical advisory states (``passed`` / ``failed`` /
``running`` / ``no_runs``), and returns the structured payload.

GitHub Actions ``queued`` collapses into ``running`` by operator policy:
pre-run and in-progress share one "work in flight"
classification.

This handler is deliberately SINGLE-SHOT: wait/poll semantics live
client-side in the ``yoke github-actions check-ci --wait`` adapter
(:mod:`yoke_cli.commands.adapters.github_actions`), which
re-dispatches this point-in-time check on its own sleep/timeout budget.
A server-side wait loop blocks one ``POST /v1/functions/call`` for the
whole CI wait and exceeds the https relay's read timeout (the client
reports ``https_transport_failed`` while the server keeps polling).
Legacy ``wait``/``timeout_sec`` payload keys from
older clients are ignored by pydantic's default extra-field handling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


_RUNNING_STATUSES = frozenset({"queued", "in_progress", "pending", "waiting"})


class CheckCiRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    workflow: str = Field(..., min_length=1, description="Workflow file (e.g. ci.yml).")
    branch: str = Field("main", description="Branch to inspect (default: main).")
    project: str = Field("yoke", description="Project capability owning the GitHub App repo binding.")


class CheckCiResponse(BaseModel):
    # passed | failed | running | no_runs. The CLI adapter's client-side
    # wait loop additionally synthesizes "timeout" on budget exhaustion.
    state: str
    run_id: Optional[int] = None
    html_url: Optional[str] = None
    status: Optional[str] = None
    conclusion: Optional[str] = None


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code="invalid_payload", message=message, jsonpath=jsonpath,
        ),
    )


def _auth_failed(message: str, *, repair_hint: str = "") -> HandlerOutcome:
    full = f"{message}\n  Repair: {repair_hint}" if repair_hint else message
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="project_auth_error", message=full),
    )


def _transport_failed(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code="rest_transport_error", message=message),
    )


def _classify(run: Optional[Dict[str, Any]]) -> CheckCiResponse:
    """Translate the latest ``workflow_runs[0]`` payload into a typed response."""
    if not run:
        return CheckCiResponse(state="no_runs")
    run_id = run.get("id")
    if not isinstance(run_id, int) or run_id <= 0:
        return CheckCiResponse(state="no_runs")

    status = str(run.get("status") or "").strip()
    conclusion = str(run.get("conclusion") or "").strip() or None
    html_url = str(run.get("html_url") or "").strip() or None

    if status == "completed":
        state = "passed" if conclusion == "success" else "failed"
    elif status in _RUNNING_STATUSES:
        state = "running"
    else:
        state = "failed" if status else "no_runs"

    return CheckCiResponse(
        state=state,
        run_id=run_id,
        html_url=html_url,
        status=status or None,
        conclusion=conclusion,
    )


def handle_check_ci(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _bad_request(
            "target.kind must be 'global' (github_actions.check_ci has no item binding)",
            jsonpath="$.target.kind",
        )

    try:
        payload = CheckCiRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    if "/" not in payload.repo:
        return _bad_request(
            f"repo must be owner/name, got {payload.repo!r}",
            jsonpath="$.payload.repo",
        )

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import latest_workflow_run
    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        repair_command_hint,
        resolve_project_github_auth,
    )

    try:
        resolved = resolve_project_github_auth(payload.project)
    except ProjectGithubAuthError as exc:
        return _auth_failed(
            f"{exc.code}: {exc}",
            repair_hint=repair_command_hint(exc, payload.project),
        )

    try:
        run = latest_workflow_run(
            payload.repo,
            payload.workflow,
            branch=payload.branch,
            token=resolved.token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"latest_workflow_run failed: {exc}")

    return HandlerOutcome(
        result_payload=_classify(run).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github_actions.check_ci",
        "handler": handle_check_ci,
        "request_model": CheckCiRequest,
        "response_model": CheckCiResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_actions_check_ci",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "CheckCiRequest",
    "CheckCiResponse",
    "REGISTRATIONS",
    "handle_check_ci",
]
