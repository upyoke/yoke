"""Bind function-call actor identity to the ambient harness session.

The dispatcher trusts ``FunctionCallRequest.actor.session_id`` as the
caller's declared harness session. This helper resolves the ambient
caller session (env chain, then the hook-written process-anchor
registry — :mod:`yoke_core.domain.session_ambient_identity`),
classifies the function as read-only or mutating from its registry
metadata, and returns a bound copy of the request or a typed error.

Transport-symmetric identity rules (in-process and https resolve by the
same rules; the https boundary supplies the envelope session as the
ambient because the caller's environment lives client-side):

- The explicit payload session wins when present. A payload session that
  diverges from the resolved ambient is the flagged operator-debug
  override path (``explicit_override``), recorded in dispatcher event
  context — never silently trusted.
- The resolved ambient fills in when the payload carries no session.
- A mutating function whose registry entry requires an ambient session
  rejects with ``actor_session_missing`` only when *neither* source
  yields a session. That state is a Yoke infrastructure gap (hook
  registration / process-anchor resolution failed), not something for
  agents to work around with env exports.
- ``actor_id`` is resolved server-side from ``harness_sessions`` keyed
  on the bound session; a contradicting payload ``actor_id`` still
  denies mutating calls (``actor_id_mismatch``). The same lookup also
  reports whether the bound session has a ``harness_sessions`` row at
  all (``session_registered``) so the dispatcher can mark events from
  unregistered sessions ``provenance_unverified`` with zero extra
  queries.

Public surface:

- :func:`is_read_only` — registry-metadata classifier.
- :func:`bind_actor_identity` — main entry point used by the dispatcher.
- :class:`BoundIdentity` — return shape carrying the bound request,
  payload/ambient session ids, override + registration findings, and an
  optional error response.
- :class:`ActorLookup` / ``ActorIdResolver`` — the session→actor lookup
  contract (``actor_id`` plus the row-existence finding).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.session_ambient_identity import (
    resolve_ambient_session_id,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry


@dataclass(frozen=True)
class ActorLookup:
    """Outcome of one ``harness_sessions`` lookup for a session id.

    ``session_found`` is ``True`` when a row exists, ``False`` when the
    lookup positively found no row, and ``None`` when the lookup could
    not run (no session id, DB unavailable) — only a positive ``False``
    may drive provenance marking.
    """

    actor_id: Optional[str] = None
    session_found: Optional[bool] = None


ActorIdResolver = Callable[[str], ActorLookup]


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def is_read_only(entry: RegistryEntry) -> bool:
    """An entry is read-only only when it takes no claim and has no side effects."""
    return entry.claim_required_kind is None and not entry.side_effects


@dataclass(frozen=True)
class BoundIdentity:
    """Outcome of an identity-binding attempt.

    ``error`` carries a populated :class:`FunctionCallResponse` when the
    bind failed; ``bound_request`` is ``None`` in that case. Otherwise
    ``bound_request`` carries the bound session (payload-first, ambient
    fill-in). ``explicit_override`` marks the operator-debug path where
    the payload session was not corroborated by ambient resolution;
    ``session_registered`` carries the ``harness_sessions`` row-existence
    finding for the bound session (``None`` when no lookup ran).
    """

    bound_request: Optional[FunctionCallRequest]
    payload_session_id: str
    ambient_session_id: str
    error: Optional[FunctionCallResponse] = None
    explicit_override: bool = False
    session_registered: Optional[bool] = None


def _error_response(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    *,
    code: str,
    message: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(code=code, message=message),
        event_ids=[],
    )


def _default_actor_id_resolver(session_id: str) -> ActorLookup:
    """Canonical lookup surface for function-call actor identity.

    Reads ``harness_sessions.actor_id`` keyed on session_id via the
    canonical control-plane DB. ``session_found=False`` is a positive
    no-row finding (the provenance-marking signal); transient DB errors
    report ``session_found=None`` so a broken lookup never marks a
    registered session unverified.

    A sibling private helper exists at
    ``yoke_core.domain.migration_apply_audit._resolve_session_actor_id``
    for audit-row enrichment (best-effort, silently ignores misses). The
    semantic contract differs: this helper drives denial/provenance
    decisions in the dispatcher, while the audit helper is opportunistic.
    The two are deliberately not extracted to a shared surface; the SQL
    literal is the only overlap.
    """
    if not session_id:
        return ActorLookup()
    try:
        from yoke_core.domain import db_helpers
    except Exception:
        return ActorLookup()
    try:
        with db_helpers.connect() as conn:
            return _read_actor_lookup(conn, session_id)
    except db_backend.operational_error_types():
        return ActorLookup()
    except (AttributeError, RuntimeError, TypeError):
        return ActorLookup()


def _read_actor_lookup(conn: Any, session_id: str) -> ActorLookup:
    """Resolve ``(actor_id, row-exists)`` for ``session_id``; never raises."""
    try:
        p = _placeholder(conn)
        row = conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return ActorLookup()
    if row is None:
        return ActorLookup(actor_id=None, session_found=False)
    try:
        value = row[0]
    except (KeyError, IndexError, TypeError):
        return ActorLookup(actor_id=None, session_found=True)
    if value is None:
        return ActorLookup(actor_id=None, session_found=True)
    return ActorLookup(actor_id=str(value), session_found=True)


def bind_actor_identity(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    *,
    ambient_session_id: Optional[str] = None,
    actor_id_resolver: Optional[ActorIdResolver] = None,
) -> BoundIdentity:
    """Resolve ambient identity and return a bound request or an error response.

    ``ambient_session_id`` overrides the ambient chain (env →
    process-anchor ancestry). The https boundary passes the envelope
    session here (possibly ``""``) so the server never consults its own
    environment for the caller's identity; pass ``None`` to resolve the
    local ambient chain.

    ``actor_id_resolver`` overrides the canonical ``harness_sessions``
    lookup; tests inject a callable returning :class:`ActorLookup`.
    """
    if ambient_session_id is None:
        ambient_session_id = resolve_ambient_session_id() or ""
    if actor_id_resolver is None:
        actor_id_resolver = _default_actor_id_resolver

    payload_session = request.actor.session_id or ""
    read_only = is_read_only(entry)

    # Transport-symmetric bound identity: the explicit payload session
    # wins when present (operator-debug override when uncorroborated by
    # ambient resolution); the resolved ambient fills in otherwise.
    bound_session = payload_session or ambient_session_id
    explicit_override = bool(payload_session) and payload_session != ambient_session_id

    if not read_only and entry.ambient_session_required and not bound_session:
        return BoundIdentity(
            bound_request=None,
            payload_session_id=payload_session,
            ambient_session_id="",
            error=_error_response(
                request, entry,
                code="actor_session_missing",
                message=(
                    f"mutating function {entry.function_id!r} could not "
                    "resolve an ambient harness session for this process. "
                    "This is a Yoke infrastructure gap (session "
                    "registration or process-anchor resolution failed), "
                    "not something to work around — file a field-note if "
                    "you can, otherwise report it to the operator. "
                    "Operator-debug only: an explicit session id "
                    "(--session-id) overrides ambient resolution."
                ),
            ),
        )

    if not bound_session:
        return BoundIdentity(
            bound_request=request,
            payload_session_id=payload_session,
            ambient_session_id=ambient_session_id,
            error=None,
        )

    if request.actor.session_id == bound_session:
        bound = request
    else:
        new_actor = request.actor.model_copy(
            update={"session_id": bound_session}
        )
        bound = request.model_copy(update={"actor": new_actor})

    return _bind_actor_id(
        entry,
        bound,
        payload_session_id=payload_session,
        ambient_session_id=ambient_session_id,
        actor_id_resolver=actor_id_resolver,
        read_only=read_only,
        explicit_override=explicit_override,
    )


def _bind_actor_id(
    entry: RegistryEntry,
    bound_request: FunctionCallRequest,
    *,
    payload_session_id: str,
    ambient_session_id: str,
    actor_id_resolver: ActorIdResolver,
    read_only: bool,
    explicit_override: bool,
) -> BoundIdentity:
    """Resolve actor_id server-side and decide bind / pass-through / deny.

    Mutating functions deny on a contradicting payload actor_id;
    read-only functions resolve best-effort and never deny on the
    actor_id axis. The lookup's row-existence finding rides out on
    ``session_registered`` for provenance marking.
    """
    payload_actor_id = (bound_request.actor.actor_id or "").strip()
    bound_session_id = bound_request.actor.session_id
    lookup = actor_id_resolver(bound_session_id)
    resolved_actor_id = lookup.actor_id or ""

    if payload_actor_id and resolved_actor_id and payload_actor_id != resolved_actor_id:
        if read_only:
            return BoundIdentity(
                bound_request=bound_request,
                payload_session_id=payload_session_id,
                ambient_session_id=ambient_session_id,
                explicit_override=explicit_override,
                session_registered=lookup.session_found,
            )
        return BoundIdentity(
            bound_request=None,
            payload_session_id=payload_session_id,
            ambient_session_id=ambient_session_id,
            session_registered=lookup.session_found,
            error=_error_response(
                entry=entry,
                request=bound_request,
                code="actor_id_mismatch",
                message=(
                    f"mutating function {entry.function_id!r} payload "
                    f"actor_id {payload_actor_id!r} does not match the "
                    f"actor_id resolved from harness_sessions for "
                    f"session_id {bound_session_id!r} ({resolved_actor_id!r})."
                ),
            ),
        )

    if not payload_actor_id and resolved_actor_id:
        new_actor = bound_request.actor.model_copy(
            update={"actor_id": resolved_actor_id}
        )
        bound_request = bound_request.model_copy(update={"actor": new_actor})

    # Empty payload + missing resolved value, or non-empty payload +
    # missing resolved value: leave as-is. Downstream gates (claim
    # verification, handler resolution) reject unregistered sessions
    # naturally; the binder reports the row-existence finding so the
    # dispatcher marks the call's events instead of silently trusting
    # an unverifiable session string.
    return BoundIdentity(
        bound_request=bound_request,
        payload_session_id=payload_session_id,
        ambient_session_id=ambient_session_id,
        explicit_override=explicit_override,
        session_registered=lookup.session_found,
    )


__all__ = [
    "ActorIdResolver",
    "ActorLookup",
    "BoundIdentity",
    "bind_actor_identity",
    "is_read_only",
]
