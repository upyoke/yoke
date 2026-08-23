"""Narrow hook port for one durable peer-broker wake reservation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BrokerWakeLease:
    attempt_id: str
    lease_id: str
    command: str


class SessionBrokerWakePort(Protocol):
    def lease_for_hook(
        self, *, broker_session_id: str, hook_event: str
    ) -> BrokerWakeLease | None: ...

    def complete_hook_lease(
        self,
        *,
        lease_id: str,
        delivered: bool,
        result: str,
    ) -> None: ...


class CoreSessionBrokerWakePort:
    def lease_for_hook(
        self, *, broker_session_id: str, hook_event: str
    ) -> BrokerWakeLease | None:
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook

        conn = db_backend.connect(busy_timeout_ms=2000)
        try:
            lease = lease_broker_wake_for_hook(
                conn,
                broker_session_id=broker_session_id,
                hook_event=hook_event,
            )
            if lease is None:
                return None
            return BrokerWakeLease(
                attempt_id=lease.attempt_id,
                lease_id=lease.lease_id,
                command=lease.command,
            )
        finally:
            conn.close()

    def complete_hook_lease(
        self,
        *,
        lease_id: str,
        delivered: bool,
        result: str,
    ) -> None:
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_broker_wake_settlement import (
            complete_broker_hook_lease,
        )

        conn = db_backend.connect(busy_timeout_ms=2000)
        try:
            complete_broker_hook_lease(
                conn,
                lease_id=lease_id,
                delivered=delivered,
                result=result,
            )
        finally:
            conn.close()


__all__ = [
    "BrokerWakeLease",
    "CoreSessionBrokerWakePort",
    "SessionBrokerWakePort",
]
