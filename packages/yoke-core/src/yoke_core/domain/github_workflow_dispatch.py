"""Recoverable GitHub workflow dispatch over durable intent state."""

from __future__ import annotations

import hashlib
from typing import Any

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_PREFIX,
    workflow_dispatch_marker,
)
from yoke_core.domain.github_workflow_dispatch_intents import (
    DispatchIntent,
    DispatchIntentStoreError,
    claim_attempt,
    complete_intent,
    latest_intent,
    reject_intent,
)
from yoke_core.domain.yoke_function_idempotency_scope import (
    idempotency_payload_checksum,
)


_CORRELATION_SEARCH_PAGES = 5
_CORRELATION_RUNS_PER_PAGE = 100


def _error(code: str, message: str, *, recovery_hint: str = "") -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code=code,
            message=message,
            recovery_hint=recovery_hint or None,
        ),
    )


def _response(intent: DispatchIntent, *, dispatched: bool) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={
            "dispatched": dispatched,
            "run_id": intent.workflow_run_id,
            "run_url": intent.run_url,
            "html_url": intent.html_url,
        },
        primary_success=True,
    )


def _request_scope(request: FunctionCallRequest) -> tuple[str, str, str] | None:
    request_id = str(request.request_id or "").strip()
    actor_id = str(request.actor.actor_id or "").strip()
    project_id = request.options.get("authorized_project_id")
    if not request_id or not actor_id or project_id in (None, ""):
        return None
    return request_id, actor_id, f"project:{int(project_id)}"


def _correlation_id(
    request_id: str,
    actor_id: str,
    authorization_scope: str,
    payload_checksum: str,
    attempt: int,
) -> str:
    source = "\0".join(
        (request_id, actor_id, authorization_scope, payload_checksum, str(attempt))
    )
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    return f"{WORKFLOW_DISPATCH_CORRELATION_PREFIX}{digest}"


def _same_logical_request(
    intent: DispatchIntent,
    *,
    actor_id: str,
    authorization_scope: str,
    payload_checksum: str,
) -> bool:
    return (
        intent.actor_id == actor_id
        and intent.authorization_scope == authorization_scope
        and intent.payload_checksum == payload_checksum
    )


def _correlated_run(payload: Any, intent: DispatchIntent, token: str) -> Any:
    from yoke_core.domain.github_actions_rest import rest_get

    marker = workflow_dispatch_marker(intent.correlation_id)
    for page in range(1, _CORRELATION_SEARCH_PAGES + 1):
        data = rest_get(
            f"/repos/{payload.repo}/actions/workflows/{payload.workflow}/runs",
            query={
                "event": "workflow_dispatch",
                "per_page": str(_CORRELATION_RUNS_PER_PAGE),
                "page": str(page),
            },
            token=token,
        )
        if not isinstance(data, dict) or not isinstance(
            data.get("workflow_runs"), list,
        ):
            raise ValueError("workflow correlation lookup returned malformed data")
        runs = data["workflow_runs"]
        matches = []
        for run in runs:
            if not isinstance(run, dict):
                raise ValueError(
                    "workflow correlation lookup contained a malformed run"
                )
            if marker in str(run.get("display_title") or ""):
                matches.append(run)
        if len(matches) > 1:
            raise ValueError(
                "multiple workflow runs expose dispatch correlation "
                f"{intent.correlation_id}"
            )
        if matches:
            return matches[0]
        if len(runs) < _CORRELATION_RUNS_PER_PAGE:
            break
    return None


def _exact_run_classification(payload: Any, intent: DispatchIntent, token: str) -> str:
    from yoke_core.domain.github_actions_rest import rest_get

    run = rest_get(
        f"/repos/{payload.repo}/actions/runs/{intent.workflow_run_id}",
        token=token,
    )
    if not isinstance(run, dict):
        raise ValueError("exact workflow run lookup returned malformed data")
    if str(run.get("id") or "") != intent.workflow_run_id:
        raise ValueError("exact workflow run lookup returned a different run id")
    status = str(run.get("status") or "").strip()
    conclusion = str(run.get("conclusion") or "").strip()
    if status in {"queued", "pending", "waiting", "requested", "in_progress"}:
        return "active"
    if status == "completed" and conclusion == "success":
        return "success"
    if status == "completed" and conclusion:
        return "failed"
    raise ValueError(
        "exact workflow run lookup returned an unknown state "
        f"(status={status!r}, conclusion={conclusion!r})"
    )


def _complete_from_run(intent: DispatchIntent, run: Any) -> DispatchIntent:
    run_id = str(run.get("id") or "")
    if not run_id:
        raise ValueError("correlated workflow run omitted id")
    return complete_intent(
        intent,
        workflow_run_id=run_id,
        run_url=str(run.get("url") or "") or None,
        html_url=str(run.get("html_url") or "") or None,
    )


def _claim_and_post(
    request: FunctionCallRequest,
    payload: Any,
    token: str,
    *,
    request_id: str,
    actor_id: str,
    authorization_scope: str,
    payload_checksum: str,
    attempt: int,
) -> HandlerOutcome:
    correlation_id = _correlation_id(
        request_id, actor_id, authorization_scope, payload_checksum, attempt,
    )
    claimed = claim_attempt(
        request_id=request_id,
        attempt=attempt,
        actor_id=actor_id,
        authorization_scope=authorization_scope,
        payload_checksum=payload_checksum,
        repo=payload.repo,
        workflow=payload.workflow,
        workflow_ref=payload.ref,
        inputs=payload.inputs,
        correlation_id=correlation_id,
    )
    if not claimed:
        return dispatch_workflow_with_intent(request, payload, token)
    intent = latest_intent(request_id)
    if intent is None or intent.attempt != attempt:
        raise DispatchIntentStoreError("claimed workflow dispatch intent disappeared")

    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.github_actions_rest import rest_post

    body_inputs = dict(payload.inputs)
    body_inputs[payload.correlation_input] = correlation_id
    body: dict[str, Any] = {
        "ref": payload.ref,
        "inputs": body_inputs,
        "return_run_details": True,
    }
    try:
        result = rest_post(
            f"/repos/{payload.repo}/actions/workflows/{payload.workflow}/dispatches",
            body=body,
            token=token,
            max_attempts=1,
        )
    except RestTransportError as exc:
        if exc.status is not None and 400 <= exc.status < 500:
            reject_intent(intent)
            return _error(
                "workflow_dispatch_rejected",
                f"GitHub definitively rejected workflow dispatch: {exc}",
            )
        return _error(
            "workflow_dispatch_ambiguous",
            "workflow dispatch response was lost after its durable intent was recorded",
            recovery_hint=(
                f"Retry with the same request_id {request_id!r}; Yoke will recover "
                "the GitHub run by its visible correlation marker without reposting."
            ),
        )
    if not isinstance(result, dict) or not result.get("workflow_run_id"):
        return _error(
            "workflow_dispatch_ambiguous",
            "workflow dispatch response omitted workflow_run_id after POST",
            recovery_hint=f"Retry with the same request_id {request_id!r}.",
        )
    completed = complete_intent(
        intent,
        workflow_run_id=str(result["workflow_run_id"]),
        run_url=str(result.get("run_url") or "") or None,
        html_url=str(result.get("html_url") or "") or None,
    )
    return _response(completed, dispatched=True)


def dispatch_workflow_with_intent(
    request: FunctionCallRequest,
    payload: Any,
    token: str,
) -> HandlerOutcome:
    """Dispatch, recover, replay, or retrigger one scoped logical request."""
    scope = _request_scope(request)
    if scope is None:
        return _error(
            "workflow_dispatch_scope_required",
            "workflow dispatch requires request_id, authenticated actor, and "
            "authorized project scope",
        )
    request_id, actor_id, authorization_scope = scope
    payload_checksum = idempotency_payload_checksum(request)
    try:
        intent = latest_intent(request_id)
        if intent is not None and not _same_logical_request(
            intent,
            actor_id=actor_id,
            authorization_scope=authorization_scope,
            payload_checksum=payload_checksum,
        ):
            return _error(
                "idempotency_key_collision",
                "request_id was already bound to a different actor, authorized "
                "scope, or canonical workflow payload",
            )
        if intent is None or intent.state == "rejected":
            return _claim_and_post(
                request,
                payload,
                token,
                request_id=request_id,
                actor_id=actor_id,
                authorization_scope=authorization_scope,
                payload_checksum=payload_checksum,
                attempt=1 if intent is None else intent.attempt + 1,
            )
        if intent.state == "pending":
            run = _correlated_run(payload, intent, token)
            if run is None:
                return _error(
                    "workflow_dispatch_pending",
                    "a durable workflow dispatch intent exists, but its correlated "
                    "GitHub run is not visible in the bounded recent-run search "
                    f"(up to {_CORRELATION_SEARCH_PAGES * _CORRELATION_RUNS_PER_PAGE} "
                    "runs); no duplicate POST was sent",
                    recovery_hint=f"Retry with the same request_id {request_id!r}.",
                )
            intent = _complete_from_run(intent, run)
        classification = _exact_run_classification(payload, intent, token)
        if classification != "failed":
            return _response(intent, dispatched=False)
        return _claim_and_post(
            request,
            payload,
            token,
            request_id=request_id,
            actor_id=actor_id,
            authorization_scope=authorization_scope,
            payload_checksum=payload_checksum,
            attempt=intent.attempt + 1,
        )
    except DispatchIntentStoreError as exc:
        return _error("workflow_dispatch_state_unavailable", str(exc))
    except (TypeError, ValueError) as exc:
        return _error("rest_transport_error", str(exc))
    except Exception as exc:
        from yoke_core.domain.gh_rest_transport import RestTransportError

        if isinstance(exc, RestTransportError):
            return _error("rest_transport_error", str(exc))
        raise


__all__ = ["dispatch_workflow_with_intent"]
