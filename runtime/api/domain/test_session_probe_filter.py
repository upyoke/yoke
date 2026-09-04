"""A harness startup probe is audit history, never a roster row.

One "New" click in Claude Desktop registered three sessions: the real
conversation plus two one-second processes that sent no prompt and called no
tool. The roster read must show the conversation and hide the probes while
keeping every row in ``harness_sessions``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.session_holdings import insert_session, iso
from yoke_core.domain.session_probe import (
    FIRST_USER_PROMPT_EVENT_NAME,
    PROBE_MAX_LIFETIME_SECONDS,
)
from yoke_core.domain.sessions_list_read import list_sessions


def _later(seconds: int) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_first_prompt(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_kind, event_type, "
        "source_type, service, session_id, severity, created_at) "
        "VALUES (%s,%s,'system','session_lifecycle','hook','yoke_core.hooks',"
        "%s,'INFO',%s)",
        (
            f"evt-{session_id}",
            FIRST_USER_PROMPT_EVENT_NAME,
            session_id,
            iso(),
        ),
    )
    conn.commit()


def test_probe_session_is_hidden_while_real_sessions_are_listed(test_db):
    insert_session(test_db, "s-probe", ended_at=iso())
    insert_session(test_db, "s-live")
    insert_session(
        test_db,
        "s-short-conversation",
        ended_at=_later(PROBE_MAX_LIFETIME_SECONDS - 5),
    )
    _record_first_prompt(test_db, "s-short-conversation")
    insert_session(
        test_db,
        "s-long-quiet-session",
        ended_at=_later(PROBE_MAX_LIFETIME_SECONDS + 5),
    )

    listed = {row["session_id"] for row in list_sessions()}

    assert "s-probe" not in listed
    assert listed >= {"s-live", "s-short-conversation", "s-long-quiet-session"}
    kept = test_db.execute(
        "SELECT COUNT(*) FROM harness_sessions WHERE session_id = %s",
        ("s-probe",),
    ).fetchone()[0]
    assert int(kept) == 1, "the probe row stays in the database for audit"
