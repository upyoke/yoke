"""Narrow hook-to-message-core delivery port.

The hook evaluator owns presentation, while the message domain owns durable
leases and recipient state. Keeping that seam explicit lets hook tests prove
rendering and settlement without constructing a control-plane database.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class LeasedSessionMessage:
    """One authenticated message body returned under a hook lease."""

    message_id: str
    body: str
    sender_actor_id: int
    sender_actor_label: str | None = None
    sender_actor_kind: str | None = None
    sender_session_id: str | None = None
    sender_surface: str | None = None
    sender_surface_label: str | None = None


@dataclass(frozen=True)
class SessionMessageLease:
    """A batch leased atomically for one recipient hook invocation.

    ``report`` carries a control-plane block composed for this recipient and
    rendered alongside the messages. It is empty for every recipient that is
    not owed one, which is almost all of them. The ``report_*`` fields are
    populated exactly when ``report`` is non-empty, and are the identity the
    hook layer hands back to :meth:`SessionMessageDeliveryPort.confirm_report_delivered`
    once it knows the rendered reply actually carried the text — composing a
    report does not by itself spend its delivery interval.
    """

    lease_id: str
    messages: tuple[LeasedSessionMessage, ...]
    remaining_count: int = 0
    report: str = ""
    report_fingerprint: str = ""
    report_claimed_at: str = ""
    report_not_after: str = ""


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

    def confirm_report_delivered(
        self,
        *,
        session_id: str,
        fingerprint: str,
        claimed_at: str,
        not_after: str,
    ) -> None: ...

    def probe_undelivered(
        self,
        *,
        session_id: str,
        hook_event: str,
        reason: str,
        detail: str = "",
    ) -> int: ...


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
                sender_actor_label=row.get("sender_actor_label"),
                sender_actor_kind=row.get("sender_actor_kind"),
                sender_session_id=row.get("sender_session_id"),
                sender_surface=row.get("sender_surface"),
                sender_surface_label=row.get("sender_surface_label"),
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
        remaining_count=max(0, int(payload.get("remaining_count") or 0)),
        report=str(payload.get("report") or ""),
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
            lease = _coerce_lease(
                lease_for_hook(
                    conn,
                    session_id=session_id,
                    hook_event=hook_event,
                    limit=limit,
                )
            )
            candidate = self._report_candidate(conn, session_id)
            if candidate is None:
                return lease
            report_fields = dict(
                report=candidate.text,
                report_fingerprint=candidate.fingerprint,
                report_claimed_at=candidate.claimed_at,
                report_not_after=candidate.not_after,
            )
            if lease is not None:
                return replace(lease, **report_fields)
            # No message lease at all, but a report is owed independently of
            # one — a steering session with an empty inbox is still owed its
            # fleet report at model-visible hook boundaries.
            return SessionMessageLease(lease_id="", messages=(), **report_fields)
        finally:
            conn.close()

    @staticmethod
    def _report_candidate(conn: Any, session_id: str) -> Any:
        """Peek the fleet report this delivery may owe its recipient, if any.

        Composed after the lease commits so the ranking read never runs
        inside the lease's lock window. Read-only and best-effort: composing
        never claims the delivery interval, so a report lost to a sibling
        denial or a malformed reply leaves the next hook free to retry
        rather than costing the recipient its messages OR a whole interval.
        """
        from yoke_core.domain.steering_fleet_report_delivery import (
            steering_report_candidate,
        )

        try:
            return steering_report_candidate(conn, session_id=session_id)
        except Exception:
            return None

    def confirm_report_delivered(
        self,
        *,
        session_id: str,
        fingerprint: str,
        claimed_at: str,
        not_after: str,
    ) -> None:
        """Claim the report interval now that the reply confirms delivery."""
        from yoke_core.domain import db_backend
        from yoke_core.domain.steering_fleet_report_delivery import (
            SteeringReportCandidate,
            confirm_steering_report_delivery,
        )

        conn = db_backend.connect(busy_timeout_ms=2000)
        try:
            confirm_steering_report_delivery(
                conn,
                SteeringReportCandidate(
                    text="",
                    session_id=session_id,
                    fingerprint=fingerprint,
                    claimed_at=claimed_at,
                    not_after=not_after,
                ),
            )
        except Exception:
            pass
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

    def probe_undelivered(
        self,
        *,
        session_id: str,
        hook_event: str,
        reason: str,
        detail: str = "",
    ) -> int:
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_message_delivery_probe import (
            record_undelivered_receipts,
        )

        conn = db_backend.connect(busy_timeout_ms=2000)
        try:
            return record_undelivered_receipts(
                conn,
                session_id=session_id,
                hook_event=hook_event,
                reason=reason,
                detail=detail,
            )
        finally:
            conn.close()


__all__ = [
    "CoreSessionMessageDeliveryPort",
    "LeasedSessionMessage",
    "SessionMessageDeliveryPort",
    "SessionMessageLease",
]
