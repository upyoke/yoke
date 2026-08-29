"""Mark a durable receipt so native resume can reach a session that is not running."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_core.domain import db_backend, json_helper


def mark_explicit_stopped_wake(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    messageability: Mapping[str, Any] | None = None,
) -> None:
    """Set ``explicit_stopped_wake`` on the recipient routing snapshot.

    Hook injection only attaches while the recipient is making tool calls.
    A session that has ended its turn, or ended entirely, makes none — so a
    landing notification (or any other push) has to take the stopped-session
    native-resume route rather than waiting for a hook that will never fire.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT routing_snapshot FROM session_message_recipients "
        f"WHERE message_id={marker} AND session_id={marker}",
        (message_id, session_id),
    ).fetchone()
    if row is None:
        return
    raw = row[0]
    if isinstance(raw, Mapping):
        snapshot = dict(raw)
    else:
        loaded = json_helper.loads_text(str(raw or "{}"))
        snapshot = dict(loaded) if isinstance(loaded, Mapping) else {}
    if messageability is not None:
        snapshot["messageability"] = dict(messageability)
    snapshot[EXPLICIT_WAKE_ROUTING_FLAG] = True
    conn.execute(
        "UPDATE session_message_recipients SET routing_snapshot="
        + marker
        + f" WHERE message_id={marker} AND session_id={marker}",
        (
            json_helper.dumps_compact(dict(sorted(snapshot.items()))),
            message_id,
            session_id,
        ),
    )


__all__ = ["mark_explicit_stopped_wake"]
