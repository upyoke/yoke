# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from dataclasses import replace

from datetime import timedelta

import pytest

from runtime.api.domain.session_org_messages_test_support import (
    org_world as org_world,
    relay,
)

from runtime.api.domain.org_scope_relay_reports_test_support import NOW, OLD, MACHINE

from yoke_core.domain.session_manual_wake import request_session_wake

from yoke_core.domain.session_message_service import send_message

from yoke_contracts.session_control.models import RecipientSelector

from yoke_core.domain.session_relay_types import RelayHeartbeat

from yoke_core.domain.session_relay_wake_claim import wake_candidates

from yoke_core.domain.session_relay_jobs import claim_wake_job

from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook

from yoke_core.domain.session_broker_wake_settlement import complete_broker_hook_lease

from yoke_core.domain.session_wake_drain_cadence import wake_work_pending

from yoke_core.domain.session_private_route_qualification import (
    qualification_for_message,
    PrivateRouteQualificationError,
)

from yoke_core.domain.session_message_types import SessionMessageError

from yoke_core.domain.session_wake_meter import meter_wall

from yoke_core.domain import session_wake_meter as meter

from yoke_core.domain import session_relay as relay_domain

from yoke_core.domain.session_recovery_facts import record_native_turn_end

from yoke_core.domain.session_vendor_error_resume import resume_vendor_error_sessions


def heartbeat(w, projects=()):
    return RelayHeartbeat(
        relay_id="org-relay",
        actor_id=w.owner,
        machine_id=MACHINE,
        hostname="org-host",
        relay_version="1.0",
        surface_versions={"codex-cli": "0.152.1"},
        project_ids=projects,
    )


def enqueue(w, target="org-target"):
    relay(w)
    return request_session_wake(
        w.conn,
        actor_id=w.owner,
        caller_session_id="org-sender",
        session_id=target,
        public_ref=None,
        prompt=None,
        now=NOW,
    )["message_id"]


def reserve(w):
    relay(w)
    w.conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id='org-target'"
    )
    send_message(
        w.conn,
        actor_id=w.owner,
        sender_session_id="org-sender",
        selector=RecipientSelector(session_ids=["org-target"]),
        body="Report the current result.",
        now=NOW - timedelta(minutes=11),
    )
    w.conn.execute("UPDATE session_relays SET connected_until=%s", (OLD,))
    w.conn.commit()
    lease = lease_broker_wake_for_hook(
        w.conn,
        broker_session_id="project-sender",
        hook_event="PreToolUse",
        now=NOW,
    )
    assert lease
    complete_broker_hook_lease(
        w.conn, lease_id=lease.lease_id, delivered=True, result="injected", now=NOW
    )
    w.conn.execute(
        "UPDATE session_relays SET connected_until=%s", (NOW + timedelta(hours=1),)
    )
    w.conn.commit()
    return lease
