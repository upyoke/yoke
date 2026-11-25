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
)
from yoke_core.domain.github_workflow_dispatch_intents import (
    DispatchIntent,
    DispatchIntentStoreError,
    claim_attempt,
    complete_intent,
    latest_intent,
    reject_intent,
)
from yoke_core.domain.github_workflow_dispatch_runs import (
    CORRELATION_RUNS_PER_PAGE,
    CORRELATION_SEARCH_PAGES,
    correlated_run,
    recorded_run,
    run_classification,
)
from yoke_core.domain.platform_consumer_dispatch_recovery import (
    ConsumerProofRecoveryError,
    is_exact_consumer_proof,
    reconcile_consumer_runs,
    validate_consumer_run,
    verify_consumer_tag,
)
from yoke_core.domain.yoke_function_idempotency_scope import (
    idempotency_payload_checksum,
)


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


def _collision(message: str, *, recovery_hint: str) -> HandlerOutcome:
    return _error("idempotency_key_collision", message, recovery_hint=recovery_hint)


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
    """Owns the mutation: this exact actor's own dispatch of this pair."""
    return (
        intent.actor_id == actor_id
        and intent.authorization_scope == authorization_scope
        and intent.payload_checksum == payload_checksum
    )


def _proof_reusable(
    intent: DispatchIntent,
    *,
    authorization_scope: str,
    payload_checksum: str,
) -> bool:
    """Proves this pair for any actor sharing (scope, payload) — not just its
    owner. Only *owning* the mutation stays actor-scoped, via
    ``_same_logical_request``.
    """
    return (
        intent.authorization_scope == authorization_scope
        and intent.payload_checksum == payload_checksum
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
    pending_predecessor: DispatchIntent | None = None,
) -> HandlerOutcome:
    correlation_id = _correlation_id(
        request_id,
        actor_id,
        authorization_scope,
        payload_checksum,
        attempt,
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
        pending_predecessor=pending_predecessor,
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
            recovery_hint=f"Retry with the same request_id {request_id!r} "
            "to reconcile the recorded attempt.",

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
    scoped = {
        "authorization_scope": authorization_scope,
        "payload_checksum": payload_checksum,
    }
    owned = {"actor_id": actor_id, **scoped}

    def _mutate(
        attempt: int, *, pending_predecessor: DispatchIntent | None = None
    ) -> HandlerOutcome:
        return _claim_and_post(
            request,
            payload,
            token,
            request_id=request_id,
            attempt=attempt,
            pending_predecessor=pending_predecessor,
            **owned,
        )

    exact_pair = is_exact_consumer_proof(payload, request_id)
    try:
        intent = latest_intent(request_id)
        if intent is not None and not _proof_reusable(intent, **scoped):
            return _collision(
                "request_id is bound to a different scope or payload",
                recovery_hint="review why this call differs from the recorded attempt",
            )
        owns = intent is not None and _same_logical_request(intent, **owned)
        if intent is None:
            return _mutate(1)
        if exact_pair and intent.state in {"pending", "rejected"}:
            matched, retry_ready = reconcile_consumer_runs(payload, intent, token)
            if matched is not None:
                matched_intent, run, classification = matched
                if matched_intent.state == "pending":
                    matched_intent = _complete_from_run(matched_intent, run)
                if classification == "no_verdict" and owns:
                    verify_consumer_tag(payload, token)
                    return _mutate(intent.attempt + 1)
                return _response(matched_intent, dispatched=False)
            if retry_ready and owns:
                verify_consumer_tag(payload, token)
                predecessor = intent if intent.state == "pending" else None
                return _mutate(intent.attempt + 1, pending_predecessor=predecessor)
            return _error(
                "workflow_dispatch_pending",
                "no usable GitHub run is visible for the recorded Platform proof attempts",
                recovery_hint=f"The original dispatching actor can retry request_id {request_id!r} "
                "after the join window with a complete GitHub lookup.",
            )
        if intent.state == "rejected":
            if owns:
                return _mutate(intent.attempt + 1)
            # Reusable pair, nothing succeeded yet; only the owner may retry.
            return _collision(
                "the latest attempt was rejected, and this actor did not dispatch it",
                recovery_hint="only the original dispatching actor may retry it",
            )
        if intent.state == "pending":
            run = correlated_run(payload, intent, token)
            if run is None:
                return _error(
                    "workflow_dispatch_pending",
                    "a durable workflow dispatch intent exists, but its correlated "
                    "GitHub run is not visible in the bounded recent-run search "
                    f"(up to {CORRELATION_SEARCH_PAGES * CORRELATION_RUNS_PER_PAGE} "
                    "runs); no duplicate POST was sent",
                    recovery_hint=f"Retry with the same request_id {request_id!r}.",
                )
            intent = _complete_from_run(intent, run)
        run = recorded_run(payload, intent, token)
        if exact_pair:
            validate_consumer_run(payload, intent, run)
        classification = run_classification(run)
        if classification != "no_verdict" or not owns:
            # Every reader reuses a run in flight or with a verdict; only the
            # owner retriggers a no-verdict run it actually owns.
            return _response(intent, dispatched=False)
        return _mutate(intent.attempt + 1)
    except ConsumerProofRecoveryError as exc:
        return _error(
            exc.code, str(exc),
            recovery_hint="Restore the exact Platform proof lookup or bound tag, "
            "then retry with the same request_id.",
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
