"""Narrow hook-to-message-core delivery port.

The hook evaluator owns presentation, while the message domain owns durable
leases and recipient state. Keeping that seam explicit lets hook tests prove
rendering and settlement without constructing a control-plane database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class LeasedSessionMessage:
    """One authenticated message body returned under a hook lease."""

    message_id: str
    body: str
    sender_actor_id: int


@dataclass(frozen=True)
class SessionMessageLease:
    """A batch leased atomically for one recipient hook invocation."""

    lease_id: str
    messages: tuple[LeasedSessionMessage, ...]


class SessionMessageDeliveryPort(Protocol):
    """Durable operations needed by the hook delivery module."""

    def read_for_hook(
        self,
        *,
        session_id: str,
        hook_event: str,
        limit: int,
    ) -> tuple[LeasedSessionMessage, ...]: ...

    def lease_for_hook(
        self,
        *,
        session_id: str,
        hook_event: str,
        limit: int,
    ) -> SessionMessageLease | None: ...

    def complete_hook_lease(
        self,
        *,
        lease_id: str,
        injected: bool,
        result: str,
    ) -> None: ...


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        payload = dump()
        if isinstance(payload, Mapping):
            return payload
    raise TypeError("message delivery result must be a mapping")


def _coerce_messages(raw_messages: Any) -> tuple[LeasedSessionMessage, ...]:
    if not isinstance(raw_messages, (list, tuple)):
        raise ValueError("message delivery result is missing its messages")
    messages: list[LeasedSessionMessage] = []
    for raw in raw_messages:
        row = _mapping(raw)
        message_id = str(row.get("message_id") or "").strip()
        body = row.get("body")
        sender_actor_id = row.get("sender_actor_id")
        if not message_id or not isinstance(body, str):
            raise ValueError("leased message is missing its id or body")
        messages.append(
            LeasedSessionMessage(
                message_id=message_id,
                body=body,
                sender_actor_id=int(sender_actor_id),
            )
        )
    return tuple(messages)


def _coerce_lease(value: Any) -> SessionMessageLease | None:
    if value is None:
        return None
    payload = _mapping(value)
    lease_id = str(payload.get("lease_id") or "").strip()
    if not lease_id:
        raise ValueError("message delivery lease is missing its id")
    return SessionMessageLease(
        lease_id=lease_id,
        messages=_coerce_messages(payload.get("messages")),
    )


class CoreSessionMessageDeliveryPort:
    """Lazy adapter to the durable message domain.

    The sibling message-plane slice provides the imported functions. Import
    and connection creation stay inside each call so an unavailable or older
    control plane fails open at the hook boundary without caching stale state.
    """

    def read_for_hook(
        self,
        *,
        session_id: str,
        hook_event: str,
        limit: int,
    ) -> tuple[LeasedSessionMessage, ...]:
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_message_observer import read_for_hook

        conn = db_backend.connect(busy_timeout_ms=2000)
        try:
            return _coerce_messages(
                read_for_hook(
                    conn,
                    session_id=session_id,
                    hook_event=hook_event,
                    limit=limit,
                )
            )
        finally:
            conn.close()

    def lease_for_hook(
        self,
        *,
        session_id: str,
        hook_event: str,
        limit: int,
    ) -> SessionMessageLease | None:
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_message_delivery import lease_for_hook

        conn = db_backend.connect(busy_timeout_ms=2000)
        try:
            return _coerce_lease(
                lease_for_hook(
                    conn,
                    session_id=session_id,
                    hook_event=hook_event,
                    limit=limit,
                )
            )
        finally:
            conn.close()

    def complete_hook_lease(
        self,
        *,
        lease_id: str,
        injected: bool,
        result: str,
    ) -> None:
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_message_delivery import complete_hook_lease

        conn = db_backend.connect(busy_timeout_ms=2000)
        try:
            complete_hook_lease(
                conn,
                lease_id=lease_id,
                injected=injected,
                result=result,
            )
        finally:
            conn.close()


__all__ = [
    "CoreSessionMessageDeliveryPort",
    "LeasedSessionMessage",
    "SessionMessageDeliveryPort",
    "SessionMessageLease",
]
