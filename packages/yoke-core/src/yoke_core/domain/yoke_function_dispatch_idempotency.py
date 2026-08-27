"""Scoped replay, collision, and in-flight function-call deduplication."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain.yoke_function_dispatch_events import emit_idempotency_replay
from yoke_core.domain.yoke_function_registry import RegistryEntry


IdempotencyReplay = Tuple[Dict[str, Any], str, str, str, str]
IdempotencyLookup = Callable[
    [str],
    Optional[IdempotencyReplay],
]


def _reservation_key(request_id: str) -> int:
    """Map one request id onto the signed bigint advisory-lock namespace."""
    digest = hashlib.sha256(
        f"function-call:{request_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _close_quietly(conn: Any) -> None:
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def request_reservation(
    entry: RegistryEntry,
    request: FunctionCallRequest,
) -> Iterator[None]:
    """Serialize concurrent copies of one side-effecting request.

    The ledger can replay only after the first successful dispatch records its
    result. A transport retry may arrive before that write, so Postgres holds a
    session advisory lock from the initial lookup through the handler and
    ledger write. A waiting copy then observes and replays the committed row.
    Session locks release automatically if the serving process disappears.

    Connection acquisition remains best-effort, matching the ledger's existing
    degraded posture. Handler-managed idempotency and read-only calls keep their
    own concurrency semantics.
    """
    if (
        not request.request_id
        or not entry.side_effects
        or "handler_managed_idempotency" in entry.guardrails
    ):
        yield
        return

    from yoke_core.domain import db_helpers
    from yoke_core.domain.control_plane_transport import local_connection_or_none

    conn = local_connection_or_none(db_helpers.connect)
    if conn is None:
        yield
        return

    lock_key = _reservation_key(request.request_id)
    try:
        conn.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
    except Exception:
        _close_quietly(conn)
        yield
        return

    try:
        yield
    finally:
        try:
            conn.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        except Exception:
            pass
        finally:
            _close_quietly(conn)


def _idempotency_lookup(
    request_id: str,
) -> Optional[IdempotencyReplay]:
    if not request_id:
        return None
    try:
        from yoke_core.domain.function_call_ledger import lookup_call

        return lookup_call(request_id)
    except Exception:
        return None


def _collision(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    message: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(code="idempotency_key_collision", message=message),
        event_ids=[],
    )


def handle_idempotency(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    *,
    identity_context: Optional[Dict[str, Any]],
    permission_key: Optional[str],
    project: Optional[str],
    authorization_scope: str,
    payload_checksum: str,
    lookup: Optional[IdempotencyLookup] = None,
) -> Optional[FunctionCallResponse]:
    """Return a replay/collision response, or None for a fresh request.

    ``lookup`` is an explicit dispatcher integration seam. Direct callers omit
    it and use this module's ledger lookup; the dispatcher supplies its bound
    seam so existing transport and handler tests can isolate persistence without
    moving replay decisions back into the routing module.
    """
    if "handler_managed_idempotency" in entry.guardrails or not request.request_id:
        return None
    lookup_call = _idempotency_lookup if lookup is None else lookup
    replay = lookup_call(request.request_id)
    if replay is None:
        return None
    result, function_id, actor_id, scope, checksum = replay
    if function_id and function_id != entry.function_id:
        return _collision(
            request,
            entry,
            "request_id reused across functions "
            f"({function_id!r} -> {entry.function_id!r})",
        )
    if (
        not actor_id
        or actor_id != str(request.actor.actor_id or "")
        or not scope
        or scope != authorization_scope
        or not checksum
        or checksum != payload_checksum
    ):
        return _collision(
            request,
            entry,
            "request_id was already bound to a different authenticated actor, "
            "authorized scope, or canonical payload",
        )
    emit_idempotency_replay(
        request,
        entry,
        identity_context=identity_context,
        permission_key=permission_key,
        project=project,
    )
    return FunctionCallResponse(
        success=True,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result=dict(result),
        warnings=[],
        error=None,
        event_ids=[],
    )


__all__ = [
    "IdempotencyLookup",
    "IdempotencyReplay",
    "handle_idempotency",
    "request_reservation",
]
