"""Shared collector admission and an acknowledged, deduplicating event sink."""

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone

from yoke_core.domain import db_helpers
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.events_writes import cmd_insert

RATE_WINDOW_SECONDS = 60
RATE_REQUESTS = 60
# Beyond this distance from receipt a client clock or a long-queued retry is
# flagged; the event is still accepted and ordered by receipt time.
CLIENT_TIME_TOLERANCE_SECONDS = 300
CLIENT_TIME_SKEW_FLAG = "client_time_skew"


def collector_identity(conn):
    """One durable signing key per universe org; never returned to the browser."""
    org_id = default_org_id(conn)
    conn.execute(
        "UPDATE organizations SET events_signing_key=%s "
        "WHERE id=%s AND events_signing_key IS NULL",
        (secrets.token_urlsafe(48), org_id),
    )
    row = conn.execute(
        "SELECT events_signing_key FROM organizations WHERE id=%s",
        (org_id,),
    ).fetchone()
    if not row or not row[0]:
        raise ValueError(
            "collector_identity_unavailable: restore the organization's boot-converged signing key"
        )
    conn.commit()
    secret = str(row[0])
    return org_id, hashlib.sha256(secret.encode()).hexdigest(), secret


def admit_client(conn, *, org_id, client, now=None):
    """Atomically count in Postgres so processes/restarts share the same budget."""
    now = int(time.time() if now is None else now)
    window = now - now % RATE_WINDOW_SECONDS
    key = hashlib.sha256(f"{org_id}:{client}".encode()).hexdigest()
    # Atomic conflict update serializes concurrent requests for this client.
    count = conn.execute(
        "INSERT INTO frontend_event_rate_limits (client_key, window_start, request_count) "
        "VALUES (%s,%s,1) ON CONFLICT(client_key) DO UPDATE SET "
        "window_start=excluded.window_start, request_count=CASE "
        "WHEN frontend_event_rate_limits.window_start=excluded.window_start "
        "THEN frontend_event_rate_limits.request_count+1 ELSE 1 END "
        "RETURNING request_count",
        (key, window),
    ).fetchone()[0]
    conn.execute(
        "DELETE FROM frontend_event_rate_limits WHERE window_start < %s",
        (window - RATE_WINDOW_SECONDS,),
    )
    conn.commit()
    return RATE_WINDOW_SECONDS - (now - window) if count > RATE_REQUESTS else 0


def write_frontend_events(
    events, *, org_id, environment, actor_id=None, received_at=None
):
    """Use the existing event gateway; retries dedupe on the browser event UUID.

    The emitter's own ``service`` and ``project`` names are kept as sent;
    the serving universe supplies the organization, environment and actor.
    ``created_at`` is the collector's receipt time, never the browser clock;
    the envelope keeps the client ``event_time`` beside ``received_at`` and
    the signed offset between them.
    """
    received_at = received_at or datetime.now(timezone.utc)
    received = received_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    for event in events:
        client_time = datetime.fromisoformat(event["event_time"].replace("Z", "+00:00"))
        if client_time.tzinfo is None:
            client_time = client_time.replace(tzinfo=timezone.utc)
        offset = round((client_time - received_at).total_seconds())
        envelope = {
            **event,
            "org_id": str(org_id),
            "actor_id": actor_id,
            "environment": environment,
        }
        envelope["received_at"] = received
        envelope["client_time_offset_seconds"] = offset
        envelope["session_id"] = "browser:" + event["session_id"]
        context = event.get("context")
        if isinstance(context, dict):
            context = {k: v for k, v in context.items() if k != "project_id"}
            if isinstance(context.get("detail"), dict):
                context["detail"] = {
                    k: v for k, v in context["detail"].items() if k != "project_id"
                }
            envelope["context"] = context
        # Frontend context is telemetry only. No browser value selects a project,
        # work item, actor, organization, or operational severity: the envelope
        # keeps the emitter's project name, but the row indexes as global.
        for key in (
            "project_id",
            "item_id",
            "task_num",
            "agent",
            "tool_name",
            "trace_id",
        ):
            envelope.pop(key, None)
        cmd_insert(
            event_id=event["event_id"],
            source_type="frontend",
            session_id=envelope["session_id"],
            event_kind="analytics",
            event_type=event["event_type"],
            event_name=event["event_name"],
            severity="INFO",
            event_outcome=event.get("event_outcome"),
            org_id=str(org_id),
            actor_id=actor_id,
            environment=environment,
            service=event["service"],
            anomaly_flags=(
                CLIENT_TIME_SKEW_FLAG
                if abs(offset) > CLIENT_TIME_TOLERANCE_SECONDS
                else None
            ),
            envelope=json.dumps(envelope, separators=(",", ":")),
            created_at=received,
            skip_severity=True,
        )


def read_collector_identity():
    with db_helpers.connect() as conn:
        return collector_identity(conn)


def consume_attribution_handoff(org_id, nonce, expires):
    """A unique insert is the authority for redemption across processes/restarts."""
    with db_helpers.connect() as conn:
        # Validation may precede expiry while storage follows it. Preserve the
        # attempted nonce and check expiry again in the atomic insert, so another
        # request's cleanup cannot make a delayed replay insertable either.
        conn.execute(
            "DELETE FROM frontend_attribution_redemptions WHERE expires_at <= %s "
            "AND NOT (org_id = %s AND nonce = %s)",
            (int(time.time()), org_id, nonce),
        )
        inserted = conn.execute(
            "INSERT INTO frontend_attribution_redemptions (org_id, nonce, expires_at) "
            "SELECT %s,%s,%s WHERE %s > EXTRACT(EPOCH FROM clock_timestamp()) "
            "ON CONFLICT (org_id, nonce) DO NOTHING RETURNING nonce",
            (org_id, nonce, expires, expires),
        ).fetchone()
        conn.commit()
        return inserted is not None
