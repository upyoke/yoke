"""Canonical authorization-scope keys for function-call replay binding."""

from __future__ import annotations

from typing import Iterable, Optional

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.yoke_function_dispatch_events import serialize_payload


def authorization_scope_key(
    *,
    permission_key: Optional[str],
    project_id: Optional[int],
    project_slug: Optional[str],
    visible_project_ids: Optional[Iterable[int]],
) -> str:
    if project_id is not None:
        return f"project:{project_id}"
    if visible_project_ids is not None:
        values = ",".join(str(value) for value in sorted(visible_project_ids))
        return f"visible_projects:{values}"
    if project_slug:
        return f"project_slug:{project_slug}"
    if permission_key:
        return f"permission:{permission_key}"
    return "authenticated_actor"


def idempotency_payload_checksum(request: FunctionCallRequest) -> str:
    """Fingerprint every request field that can change mutation semantics."""
    _, checksum = serialize_payload({
        "version": request.version,
        "target": request.target.model_dump(exclude_none=True),
        "payload": dict(request.payload),
        "preconditions": dict(request.preconditions),
        "intent": request.intent,
    })
    return checksum


__all__ = ["authorization_scope_key", "idempotency_payload_checksum"]
