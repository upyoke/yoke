"""Allowlists and dispatch for the local UI server's function proxy.

Split out of :mod:`yoke_core.ui.server` so the server module keeps only
routing and session-token security; the server re-exports the roster
names for its callers. The proxy admits a closed set of function ids:

* :data:`UI_READ_FUNCTION_ALLOWLIST` — read-only by construction, with
  one documented exception (:data:`UI_ACTIVATION_LATCH_FUNCTIONS`).
* :data:`UI_MUTATION_FUNCTION_ALLOWLIST` — the bounded browser action
  roster, dispatched as the resolved local operator actor.

Everything else is refused with 403 before the dispatcher sees it. The
browser envelope's own actor claim is never trusted: only the
server-resolved operator actor may fill ``actor_id``.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple

#: The closed roster of function ids the browser proxy may dispatch as
#: reads. Read-only by construction — registered with no side effects
#: and no claim requirement — except the documented activation-latch
#: entry below.
UI_READ_FUNCTION_ALLOWLIST = frozenset({
    "organizations.get",
    "projects.list",
    "projects.get",
    "projects.capabilities.list",
    "projects.environment_settings.get",
    "projects.infrastructure.list",
    "projects.github_binding.status",
    "items.get.run",
    "items.list.run",
    "items.overview.list",
    "items.search.run",
    "items.detail.get",
    "epic_tasks.list.run",
    "strategy.doc.list",
    "strategy.doc.get",
    "strategy.surface.list",
    "strategy.surface.get",
    "strategy.revision.diff",
    "ouroboros.entry.list",
    "board.data.get",
    "deployment_runs.list",
    "sessions.list",
    "frontier.list",
    "events.query.run",
    "doctor.last_run.get",
    "qa.method.list",
    "qa.method.get",
    "qa.plan.list",
    "qa.plan.get",
    "qa.activity.list",
    "qa.artifact.read",
    "inbox.list",
    "workflows.definition.get",
    "workflows.mechanics.get",
    "workflows.version.get",
    "test_machine.get",
    # Documented exception to "no side effects": the Overview activation
    # read latches newly satisfied module activations into
    # overview_activation_facts — universe-scoped, monotone, idempotent,
    # and carrying no actor attribution. See
    # UI_ACTIVATION_LATCH_FUNCTIONS.
    "overview.activation.get",
    "overview.vitals.get",
})

#: Read-allowlist members whose one sanctioned side effect is the
#: universe-scoped monotone activation latch. Kept as its own roster so
#: the read-only assertion over the rest of the allowlist stays exact,
#: and so these dispatch as the resolved local operator actor (when one
#: resolves) — the response's ``dismiss_available`` and per-actor
#: dismissal flags then match what the dismissal writes would do.
UI_ACTIVATION_LATCH_FUNCTIONS = frozenset({"overview.activation.get"})

#: Reads whose result is defined for the resolved local operator rather than
#: an anonymous browser process.
UI_ACTOR_BOUND_READ_FUNCTIONS = frozenset({
    "inbox.list",
    "test_machine.get",
    "workflows.mechanics.get",
})

#: The only mutations the local proxy may dispatch. All act as the resolved
#: local operator actor (:mod:`yoke_core.ui.local_operator_actor`) and are
#: refused when no operator resolves; every other mutation stays 403.
UI_MUTATION_FUNCTION_ALLOWLIST = frozenset({
    "overview.module.dismiss",
    "overview.module.restore",
    "workflows.current.set",
    "workflows.policy_defaults.publish",
    "workflows.testing_default.set",
    "workflows.delivery_default.set",
    "workflows.approval_defaults.publish",
    "test_machine.settings_replace",
    "test_machine.verify",
    "decision_requests.resolve",
    "notifications.read",
    "notifications.read_all",
    "qa.case.rerun",
    "qa.case.waive",
    "items.create",
    "sessions.reclaim_stale",
    "strategy.revision.restore",
})


def proxy_function_call(
    envelope: Dict[str, Any],
) -> Tuple[Dict[str, Any], int]:
    """Dispatch one browser envelope; return ``(payload, status_code)``."""
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.yoke_function_dispatch import dispatch

    function_id = str(envelope.get("function") or "")
    is_mutation = function_id in UI_MUTATION_FUNCTION_ALLOWLIST
    if function_id not in UI_READ_FUNCTION_ALLOWLIST and not is_mutation:
        return (
            {"error": {
                "code": "function_not_allowed",
                "message": (
                    f"function {function_id!r} is not on this UI "
                    "server's allowlist"
                ),
                "allowed": sorted(
                    UI_READ_FUNCTION_ALLOWLIST
                    | UI_MUTATION_FUNCTION_ALLOWLIST
                ),
            }},
            403,
        )
    # Actor-scoped calls act as the machine's operator, resolved
    # server-side. Reads that surface per-actor dismissal state bind the
    # operator when one resolves; mutations refuse without one.
    operator_actor_id: Optional[str] = None
    if (
        is_mutation
        or function_id in UI_ACTIVATION_LATCH_FUNCTIONS
        or function_id in UI_ACTOR_BOUND_READ_FUNCTIONS
    ):
        from yoke_core.ui.local_operator_actor import (
            resolve_local_operator_actor,
        )

        resolved = resolve_local_operator_actor()
        operator_actor_id = None if resolved is None else str(resolved)
        if (
            (is_mutation or function_id in UI_ACTOR_BOUND_READ_FUNCTIONS)
            and operator_actor_id is None
        ):
            return (
                {"error": {
                    "code": "operator_actor_unresolved",
                    "message": (
                        "this universe has no unambiguous local "
                        "operator actor, so this per-actor operation "
                        "is refused"
                    ),
                }},
                403,
            )
    raw_target = envelope.get("target")
    try:
        target = (
            TargetRef(**raw_target)
            if isinstance(raw_target, dict)
            else TargetRef(kind="global")
        )
    except Exception as exc:
        return (
            {"error": {"code": "target_invalid", "message": str(exc)}},
            422,
        )
    request = FunctionCallRequest(
        function=function_id,
        # No harness session exists in a browser: the empty session id
        # (with ambient resolution pinned off below) is the anonymous
        # local identity, same as an unbound CLI read. Only the
        # server-resolved operator actor may fill actor_id.
        actor=ActorContext(actor_id=operator_actor_id, session_id=""),
        target=target,
        request_id=str(envelope.get("request_id") or uuid.uuid4()),
        payload=dict(envelope.get("payload") or {}),
        options=dict(envelope.get("options") or {}),
    )
    # ambient_session_id="" (never None): the browser's identity lives
    # client-side, so the dispatcher must not resolve the SERVER
    # process's env/ancestry into a session.
    response = dispatch(request, ambient_session_id="")
    return response.model_dump(mode="json"), 200


__all__ = [
    "UI_ACTIVATION_LATCH_FUNCTIONS",
    "UI_ACTOR_BOUND_READ_FUNCTIONS",
    "UI_MUTATION_FUNCTION_ALLOWLIST",
    "UI_READ_FUNCTION_ALLOWLIST",
    "proxy_function_call",
]
