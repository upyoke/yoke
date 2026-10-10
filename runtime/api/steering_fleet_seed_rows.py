"""Native SQL row seeding for the disposable steering fleet."""

from datetime import datetime
import json

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.events_tool_call_outcome import OUTCOME_DENIED


NOW = "2026-08-26T12:00:00.000000Z"
LONG_AGO = "2026-08-26T09:00:00.000000Z"
BEFORE_THAT = "2026-08-26T08:00:00.000000Z"
JUST_NOW = "2026-08-26T11:58:00.000000Z"
#: Well past every seeded message's expiry, so an envelope sent at
#: :data:`LONG_AGO` is still deliverable at :data:`NOW`.
NOT_YET_EXPIRED = "2026-08-26T23:00:00.000000Z"
STAFFING_SECONDS = 5 * 60
IDLE_SECONDS = 20 * 60
SURFACE = "codex-cli"
STEERING_SESSION = "steering-holder"
WORKER_SESSION = "another-worker"
ASKER = "asking-worker"
ANSWERER = "answering-worker"
PROJECT_ID = 1
PLAN_LIMIT_HOST = "beebauman-macbook-pro-16"
#: The host name the seeded relay reports — what an unregistered machine
#: falls back to on any row that carries the relay's own hostname.
RELAY_HOSTNAME = "relay-host"
ACTOR_ID = 2


def _clock(conn, value, *, optional=False):
    native = None if optional and value is None else parse_instant(value)
    return instant_parameter(conn, native)


def seed_session(conn, session_id: str, **columns) -> None:
    """One live session, defaulting to an ordinary idle worker."""
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_level, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id, "
        "executor_surface, machine_id, last_tool_call_at, ended_at, "
        "terminated_at, current_item_id) "
        "VALUES (%s, %s, 'openai', 'test-model', 'primary', %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            columns.get("executor", "codex"),
            f"/tmp/{session_id}",
            PROJECT_ID,
            columns.get("mode", "wait"),
            _clock(conn, NOW),
            _clock(conn, NOW),
            ACTOR_ID,
            columns.get("executor_surface", SURFACE),
            columns.get("machine_id", "machine-1"),
            _clock(conn, columns.get("last_tool_call_at"), optional=True),
            _clock(conn, columns.get("ended_at"), optional=True),
            _clock(conn, columns.get("terminated_at"), optional=True),
            columns.get("current_item_id"),
        ),
    )


def seed_tool_call(
    conn,
    session_id: str,
    *,
    tool_use_id: str,
    started_at: str | datetime,
    command_summary: str,
    completed_at: str | datetime | None = None,
    tool_name: str = "Bash",
) -> None:
    """One call; unfinished calls also stamp their accepted hook's posture.

    Completed history leaves the session's current turn posture intact.
    """
    if completed_at is None:
        conn.execute(
            "UPDATE harness_sessions SET turn_posture='running', "
            "turn_posture_at=%s WHERE session_id=%s",
            (_clock(conn, started_at), session_id),
        )
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at, completed_at, "
        "command_summary) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            session_id,
            tool_use_id,
            tool_name,
            _clock(conn, started_at),
            _clock(conn, completed_at, optional=True),
            command_summary,
        ),
    )


def seed_denial(conn, session_id: str, *, tool_use_id: str, at: str | datetime) -> None:
    """Close a start row the way a PreToolUse guardrail's refusal closes it.

    The refusal stamps the call's own row rather than leaving it open with
    a separate telemetry event beside it, so a reader asks the row what
    happened and gets an answer that outlives event retention.
    """
    conn.execute(
        "UPDATE session_tool_calls SET completed_at = %s, outcome = %s "
        "WHERE session_id = %s AND tool_use_id = %s",
        (_clock(conn, at), OUTCOME_DENIED, session_id, tool_use_id),
    )


def seed_message(
    conn,
    message_id: str,
    *,
    sender: str,
    to: str,
    at: str | datetime,
    state: str = "pending",
    expires_at: str | datetime = NOT_YET_EXPIRED,
    cancelled_at: str | datetime | None = None,
    routing_snapshot: dict | None = None,
    idempotency_key: str | None = None,
) -> None:
    """One envelope and its single receipt, undelivered by default.

    ``routing_snapshot`` carries the receipt's routing facts; an explicit
    wake is one of them, so a caller that needs this receipt to read as a
    requested wake passes that flag rather than patching the row after.
    """
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at, cancelled_at, "
        "idempotency_key) "
        "VALUES (%s, %s, %s, 'a question', 'sha', %s, %s, %s, %s, %s)",
        (
            message_id,
            ACTOR_ID,
            sender,
            json.dumps({}),
            _clock(conn, at),
            _clock(conn, expires_at),
            _clock(conn, cancelled_at, optional=True),
            idempotency_key,
        ),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id, session_id, project_id, resolution_evidence, "
        "routing_snapshot, state, created_at, wake_after, injection_count) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)",
        (
            message_id,
            to,
            PROJECT_ID,
            json.dumps({}),
            json.dumps(routing_snapshot or {}),
            state,
            _clock(conn, at),
            _clock(conn, at),
        ),
    )


def seed_delivery_attempt(
    conn,
    attempt_id: str,
    *,
    message_id: str,
    to: str,
    result_code: str,
    evidence: dict | None = None,
    started_at: str | datetime = JUST_NOW,
    kind: str = "wake_relay",
) -> None:
    """One settled delivery attempt against a receipt."""
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id, message_id, target_session_id, attempt_kind, started_at, "
        "completed_at, result_code, evidence) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            attempt_id,
            message_id,
            to,
            kind,
            _clock(conn, started_at),
            _clock(conn, started_at),
            result_code,
            json.dumps(evidence or {}),
        ),
    )


def seed_relay(conn) -> None:
    """One connected relay, so a launch has somewhere it could land."""
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id, actor_id, machine_id, hostname, surface_versions, "
        "project_checkouts, first_seen_at, last_seen_at, connected_until, state) "
        "VALUES ('relay-1', %s, 'machine-1', %s, %s, %s, %s, %s, "
        "%s, 'active')",
        (
            ACTOR_ID,
            RELAY_HOSTNAME,
            json.dumps({SURFACE: "0.148.0a15"}),
            json.dumps([PROJECT_ID]),
            _clock(conn, NOW),
            _clock(conn, NOW),
            _clock(conn, NOT_YET_EXPIRED),
        ),
    )
