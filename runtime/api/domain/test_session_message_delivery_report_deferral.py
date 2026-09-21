"""Pending message leases must not wait on fleet-report ranking."""

from __future__ import annotations

import yoke_core.domain.session_message_delivery as message_delivery
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_service import send_message
from yoke_core.hooks.session_message_delivery_port import CoreSessionMessageDeliveryPort
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


class _SqliteFacade:
    """Forward to a test connection without closing it with the port."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        return None


def test_a_pending_message_lease_does_not_compose_the_fleet_report(
    monkeypatch,
) -> None:
    """Ranking after the lease is what left hook leases unused on an active session."""
    monkeypatch.setattr(message_delivery, "utc_now", lambda: NOW)
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Please re-run the focused verifier.",
        now=NOW,
    )
    called = []

    def _must_not_compose(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("report must not compose beside a message lease")

    monkeypatch.setattr(db_backend, "connect", lambda **_kwargs: _SqliteFacade(conn))
    monkeypatch.setattr(
        CoreSessionMessageDeliveryPort,
        "_report_candidate",
        staticmethod(_must_not_compose),
    )

    lease = CoreSessionMessageDeliveryPort().lease_for_hook(
        session_id="s1", hook_event="PreToolUse", limit=10
    )

    assert lease is not None
    assert lease.messages
    assert lease.report == ""
    assert called == []


def test_an_empty_inbox_still_composes_the_fleet_report(monkeypatch) -> None:
    """Deferral is only beside a pending envelope, not a ban on ranking."""
    monkeypatch.setattr(message_delivery, "utc_now", lambda: NOW)
    conn = message_connection()
    called = []

    def _compose(*_args, **_kwargs):
        called.append(True)
        return None

    monkeypatch.setattr(db_backend, "connect", lambda **_kwargs: _SqliteFacade(conn))
    monkeypatch.setattr(
        CoreSessionMessageDeliveryPort,
        "_report_candidate",
        staticmethod(_compose),
    )

    CoreSessionMessageDeliveryPort().lease_for_hook(
        session_id="s1", hook_event="PreToolUse", limit=10
    )

    assert called == [True]
