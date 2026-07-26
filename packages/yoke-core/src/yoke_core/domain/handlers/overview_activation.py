"""Overview activation-module handlers.

``overview.activation.get`` derives every module and submodule state in
one dispatch (see :mod:`yoke_core.domain.overview_activation_read`) and
latches newly satisfied activations — its one sanctioned side effect,
universe-scoped, monotone, and idempotent. The dismiss/restore pair
writes the calling actor's per-module dismissal preference and refuses
cleanly without a bound actor; module facts keep deriving either way, so
a dismissal never hides state from other actors.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain.overview_activation_read import (
    DISMISS_PREF_PREFIX,
    MODULE_KEYS,
)


class OverviewActivationGetRequest(BaseModel):
    host_facts: Optional[Dict[str, Any]] = None


class OverviewActivationGetResponse(BaseModel):
    modules: List[Dict[str, Any]]
    dismiss_available: bool


class OverviewModuleDismissRequest(BaseModel):
    module_key: str


class OverviewModuleDismissResponse(BaseModel):
    module_key: str
    dismissed: bool


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


def _require_global(
    request: FunctionCallRequest, function_id: str,
) -> Optional[HandlerOutcome]:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            f"{function_id} requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    return None


def _actor_id(request: FunctionCallRequest) -> Optional[int]:
    raw = (request.actor.actor_id or "").strip()
    return int(raw) if raw.isdigit() else None


def handle_overview_activation_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = _require_global(request, "overview.activation.get")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    host_facts = payload.get("host_facts")
    if host_facts is not None and not isinstance(host_facts, dict):
        return _error(
            "payload_invalid",
            "host_facts must be an object when present",
            jsonpath="$.payload.host_facts",
        )
    machine_connected = (host_facts or {}).get("machine_connected")
    if machine_connected is not None and not isinstance(machine_connected, bool):
        return _error(
            "payload_invalid",
            "host_facts.machine_connected must be a boolean when present",
            jsonpath="$.payload.host_facts.machine_connected",
        )

    from yoke_core.domain import db_helpers
    from yoke_core.domain.overview_activation_read import compute_activation

    conn = db_helpers.connect()
    try:
        result = compute_activation(conn, machine_connected, _actor_id(request))
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)


def _write_dismissal(
    request: FunctionCallRequest,
    function_id: str,
    *,
    dismissed: bool,
) -> HandlerOutcome:
    invalid = _require_global(request, function_id)
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    module_key = payload.get("module_key")
    if module_key not in MODULE_KEYS:
        return _error(
            "payload_invalid",
            f"module_key must be one of {', '.join(MODULE_KEYS)}",
            jsonpath="$.payload.module_key",
        )
    actor_id = _actor_id(request)
    if actor_id is None:
        return _error(
            "actor_required",
            f"{function_id} writes a per-actor preference and needs a "
            "bound actor; this caller has none",
        )

    from yoke_core.domain import db_helpers

    pref_key = DISMISS_PREF_PREFIX + module_key
    conn = db_helpers.connect()
    try:
        if dismissed:
            conn.execute(
                "INSERT INTO actor_ui_preferences "
                "(actor_id, pref_key, value, updated_at) "
                "VALUES (%s, %s, '1', %s) "
                "ON CONFLICT (actor_id, pref_key) DO UPDATE SET "
                "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
                (actor_id, pref_key, db_helpers.iso8601_now()),
            )
        else:
            conn.execute(
                "DELETE FROM actor_ui_preferences "
                "WHERE actor_id = %s AND pref_key = %s",
                (actor_id, pref_key),
            )
        conn.commit()
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"module_key": module_key, "dismissed": dismissed},
        primary_success=True,
    )


def handle_overview_module_dismiss(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    return _write_dismissal(request, "overview.module.dismiss", dismissed=True)


def handle_overview_module_restore(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    return _write_dismissal(
        request, "overview.module.restore", dismissed=False,
    )


__all__ = [
    "OverviewActivationGetRequest",
    "OverviewActivationGetResponse",
    "OverviewModuleDismissRequest",
    "OverviewModuleDismissResponse",
    "handle_overview_activation_get",
    "handle_overview_module_dismiss",
    "handle_overview_module_restore",
]
