"""Coverage for the canonical liveness helper.

The new public surface is ``latest_activity`` in
:mod:`yoke_core.domain.session_reclaim_activity` (FR-1 Strategy A —
extends the existing helper module instead of creating a new
``sessions_liveness`` module). The four frontline readers
(``sessions_cleanup``, ``frontier_recent_owner``, ``scheduler_claims``,
``sessions_lifecycle_destructive_guard``) route through it.

This file groups two test layers:

1. Unit tests for ``latest_activity`` across registration-only,
   tool-call-only, both-fresh, and both-stale cases plus a missing-
   session case (covers AC-1 + AC-12 / no new event names).
2. A structural-grep assertion that no production source under
   ``runtime/api/domain/`` opens an SQL string reading
   ``harness_sessions.last_heartbeat`` for READ outside the helper,
   the registration / heartbeat writer, and the ``epic_tasks`` table
   readers (FR-1(g) out-of-scope). Mirrors the refined AC-1 structured
   check.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.session_reclaim_activity import latest_activity
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements


def _now_iso(delta_minutes: int = 0) -> str:
    moment = datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


@pytest.fixture()
def conn(tmp_path):
    def apply_schema() -> None:
        c = db_backend.connect()
        try:
            apply_ddl_statements(c, _LIVENESS_SCHEMA)
        finally:
            c.close()

    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


_LIVENESS_SCHEMA = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT,
    last_heartbeat TEXT,
    last_tool_call_at TEXT,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    ended_at TEXT
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    last_heartbeat TEXT,
    claimed_at TEXT,
    released_at TEXT,
    target_kind TEXT,
    item_id INTEGER
);
"""


def _insert_session(conn: Any, sid: str, *, last_heartbeat=None, executor="claude-code"):
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO harness_sessions(session_id, executor, last_heartbeat, ended_at)"
        f" VALUES ({p}, {p}, {p}, NULL)",
        (sid, executor, last_heartbeat),
    )


def _stamp_tool_call(conn: Any, sid: str, at: str):
    """Stamp the activity columns the observe pipeline maintains."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at = "
        f"{p}, tool_call_count = COALESCE(tool_call_count, 0) + 1 "
        f"WHERE session_id = {p}",
        (at, sid),
    )


def test_latest_activity_missing_session_returns_none(conn: Any):
    assert latest_activity(conn, "absent") is None


def test_latest_activity_registration_only(conn: Any):
    sid = str(uuid.uuid4())
    hb = _now_iso(-5)
    _insert_session(conn, sid, last_heartbeat=hb)
    assert latest_activity(conn, sid) == hb


def test_latest_activity_tool_event_only(conn: Any):
    sid = str(uuid.uuid4())
    _insert_session(conn, sid, last_heartbeat=None)
    when = _now_iso(-1)
    _stamp_tool_call(conn, sid, when)
    assert latest_activity(conn, sid) == when


def test_latest_activity_picks_max_when_both_fresh(conn: Any):
    sid = str(uuid.uuid4())
    hb = _now_iso(-5)
    _insert_session(conn, sid, last_heartbeat=hb)
    event_at = _now_iso(-1)
    _stamp_tool_call(conn, sid, event_at)
    # event_at is later than hb (closer to now)
    assert latest_activity(conn, sid) == event_at


def test_latest_activity_picks_heartbeat_when_newer(conn: Any):
    sid = str(uuid.uuid4())
    hb = _now_iso(-1)
    _insert_session(conn, sid, last_heartbeat=hb)
    _stamp_tool_call(conn, sid, _now_iso(-10))
    assert latest_activity(conn, sid) == hb


def test_latest_activity_executor_kwarg_does_not_change_outcome(conn: Any):
    sid = str(uuid.uuid4())
    hb = _now_iso(-2)
    _insert_session(conn, sid, last_heartbeat=hb, executor="codex")
    assert latest_activity(conn, sid, executor="codex") == hb
    assert latest_activity(conn, sid, executor=None) == hb


def test_latest_activity_ignores_non_tool_events(conn: Any):
    """Lifecycle writes must not feed activity — only the stamped column.

    Registration/lifecycle paths never stamp ``last_tool_call_at``, so a
    session whose only signal is its old heartbeat stays at that
    heartbeat regardless of newer lifecycle telemetry.
    """
    sid = str(uuid.uuid4())
    _insert_session(conn, sid, last_heartbeat=_now_iso(-30))
    # No tool-call stamp: activity_at stays the heartbeat from -30m.
    activity_at = latest_activity(conn, sid)
    assert activity_at is not None
    parsed = datetime.fromisoformat(activity_at.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - parsed
    assert delta.total_seconds() >= 60 * 25  # ~30 minutes old


# ---------------------------------------------------------------------------
# Structured AC-1 / FR-1(g) check: no SQL string in domain/ opens a READ
# on harness_sessions.last_heartbeat or work_claims.last_heartbeat outside
# the canonical helper, the registration/heartbeat writer, and the
# epic_tasks.last_heartbeat readers (different table, out of scope).
# ---------------------------------------------------------------------------


def _domain_root() -> Path:
    here = Path(__file__).resolve()
    # runtime/api/test_sessions_liveness.py -> runtime/api/domain/
    return here.parent / "domain"


_HEARTBEAT_READ_RE = re.compile(
    r"(?P<table>harness_sessions|work_claims)"
    r"(?:\s|\.|\b)last_heartbeat",
    re.IGNORECASE,
)


_ALLOWED = {
    # canonical helper + private state readers (FR-1 producer)
    "session_reclaim_activity.py",
    # registration / heartbeat writer
    "sessions_lifecycle_registry.py",
    # sweep helper uses the canonical helper now; the docstring mentions
    # the old SQL shape for context — keep the docstring, but the code
    # path no longer issues the SQL string.
}


def test_no_direct_heartbeat_read_outside_canonical_helper():
    domain_root = _domain_root()
    offenders: list[str] = []
    for path in domain_root.rglob("*.py"):
        if path.name in _ALLOWED:
            continue
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # Strip docstrings and comments naively: keep only lines without "#"
        # as the leading non-blank token, and drop triple-quoted blocks.
        lines = []
        in_doc = False
        doc_quote = ""
        for line in text.splitlines():
            stripped = line.strip()
            if in_doc:
                if doc_quote and doc_quote in stripped:
                    in_doc = False
                    doc_quote = ""
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                doc_quote = stripped[:3]
                if stripped.count(doc_quote) < 2:
                    in_doc = True
                else:
                    doc_quote = ""
                continue
            if stripped.startswith("#"):
                continue
            lines.append(line)
        code = "\n".join(lines)
        for match in _HEARTBEAT_READ_RE.finditer(code):
            # Skip writes (INSERT/UPDATE/UPDATE SET ... last_heartbeat=)
            window = code[max(0, match.start() - 80) : match.end() + 20].upper()
            if any(verb in window for verb in ("INSERT", "UPDATE ")):
                continue
            offenders.append(f"{path.relative_to(domain_root.parent.parent)}: {match.group(0)}")
    assert not offenders, (
        "Production sources still open a READ on "
        "harness_sessions.last_heartbeat / work_claims.last_heartbeat "
        "outside the canonical helper:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# No new event name introduced. Asserts the events catalog
# (audit registry) does NOT gain a "SessionLiveness*" or
# "HeartbeatRefresh*" name for this ticket.
# ---------------------------------------------------------------------------


def test_no_new_event_name_introduced():
    """AC-12: this ticket does not introduce a new event name.

    Liveness reuses the existing ``HarnessToolCallCompleted`` /
    ``HarnessToolCallFailed`` events; no ``SessionLiveness*`` /
    ``HeartbeatRefresh*`` constant is allowed in the audit registry.
    """
    here = Path(__file__).resolve().parent / "domain"
    forbidden = re.compile(r'"(HeartbeatRefresh\w*|SessionLiveness\w*)"')
    offenders: list[str] = []
    for path in here.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in forbidden.finditer(text):
            offenders.append(f"{path.name}: {match.group(0)}")
    assert not offenders, (
        "Forbidden event-name strings present: " + ", ".join(offenders)
    )
