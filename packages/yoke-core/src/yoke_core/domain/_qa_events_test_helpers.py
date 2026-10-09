"""Shared fixtures and helpers for the ``test_qa_events_*`` test modules.

This module is intentionally not a ``conftest.py`` so the helpers are scoped
to the ``test_qa_events_*`` files that import them, rather than affecting
every test under ``runtime/api/domain/``.

Each split test module defines its own ``conn`` fixture (a thin wrapper
around :data:`QA_REQUIREMENTS_SCHEMA`) and imports the row helpers and
captured-event helpers from here.

The temporary tables use the active Postgres test connection with native
instant columns. They are permissive row factories: the requirement target
CHECK constraint is deliberately omitted so the suite can cover rows the
production schema forbids, such as an epic requirement without a task number.
Event emission is monkeypatched to capture envelopes rather than persist rows.
"""

from __future__ import annotations

from typing import List

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.schema_init_apply import execute_schema_script


# ---------------------------------------------------------------------------
# Permissive temporary row schema
# ---------------------------------------------------------------------------

_FIXTURE_INSTANT = parse_instant("2026-01-01T00:00:00.123456Z")

QA_REQUIREMENTS_SCHEMA = """
CREATE TEMP TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT DEFAULT 'explicit',
    success_policy TEXT,
    waived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
);
CREATE TEMP TABLE events (
    id INTEGER PRIMARY KEY,
    event_name TEXT,
    event_type TEXT,
    source_type TEXT,
    created_at TIMESTAMPTZ,
    envelope TEXT
);
"""


def make_conn():
    """Return a fresh connection with temporary permissive QA tables."""
    c = connect()
    execute_schema_script(c, QA_REQUIREMENTS_SCHEMA)
    c.commit()
    return c


# ---------------------------------------------------------------------------
# Row insertion helpers
# ---------------------------------------------------------------------------


def insert_item_requirement(conn, *, req_id=1, item_id=42):
    conn.execute(
        "INSERT INTO qa_requirements (id, item_id, qa_kind, qa_phase, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (req_id, item_id, "implementation_review", "verification", _FIXTURE_INSTANT),
    )
    conn.commit()


def insert_epic_requirement(conn, *, req_id=2, epic_id=100, task_num=3):
    conn.execute(
        "INSERT INTO qa_requirements (id, epic_id, task_num, qa_kind, qa_phase, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            req_id,
            epic_id,
            task_num,
            "implementation_review",
            "verification",
            _FIXTURE_INSTANT,
        ),
    )
    conn.commit()


def insert_deployment_requirement(conn, *, req_id=3, run_id="run-abc-001"):
    conn.execute(
        "INSERT INTO qa_requirements (id, deployment_run_id, qa_kind, qa_phase, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (req_id, run_id, "smoke", "post_deploy", _FIXTURE_INSTANT),
    )
    conn.commit()


def fetch_row(conn, req_id):
    return conn.execute(
        "SELECT item_id, epic_id, task_num, deployment_run_id FROM qa_requirements WHERE id = %s",
        (req_id,),
    ).fetchone()


# ---------------------------------------------------------------------------
# Captured-event helpers
# ---------------------------------------------------------------------------


class Captured:
    """Mimics emit_event by recording call kwargs into a list."""

    def __init__(self):
        self.calls: List[dict] = []

    def __call__(self, event_name, **kwargs):
        record = {"event_name": event_name}
        record.update(kwargs)
        self.calls.append(record)
        return record


def patch_emit_event(monkeypatch, captured):
    """Monkeypatch ``yoke_core.domain.events.emit_event`` to use captured."""
    import yoke_core.domain.events as events_module

    monkeypatch.setattr(events_module, "emit_event", captured)


def patch_emit_event_raising(monkeypatch, exc):
    import yoke_core.domain.events as events_module

    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr(events_module, "emit_event", _raise)
