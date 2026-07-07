"""Shared fixtures and helpers for the ``test_qa_events_*`` test modules.

This module is intentionally not a ``conftest.py`` so the helpers are scoped
to the ``test_qa_events_*`` files that import them, rather than affecting
every test under ``runtime/api/domain/``.

Each split test module defines its own ``conn`` fixture (a thin wrapper
around :data:`QA_REQUIREMENTS_SCHEMA`) and imports the row helpers and
captured-event helpers from here.

Classification — pure-unit-test :memory: fixture, NOT a Yoke-authority
model. The ``test_qa_events_*`` suites exercise pure row->envelope logic
(``resolve_requirement_event_target`` works on plain dicts; ``emit_qa_*_event``
always runs with ``events.emit_event`` monkeypatched, so nothing is persisted
to a real ``events`` table). The temporary tables below are just row factories.
They deliberately avoid ``qa.cmd_init`` because the schema is intentionally
permissive: ``QA_REQUIREMENTS_SCHEMA`` omits the production ``qa_requirements``
target CHECK constraint so the suite can cover edge-case rows the real schema
forbids (e.g. ``test_resolve_target_epic_no_task_num`` inserts an ``epic_id``
row with NULL ``task_num``). Routing this through the real schema would reject
those rows. This fixture does not model Yoke persistence authority.
"""

from __future__ import annotations

from typing import List

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.schema_init_apply import execute_schema_script


# ---------------------------------------------------------------------------
# In-memory DB schema
# ---------------------------------------------------------------------------

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
    waived_at TEXT,
    created_at TEXT
);
CREATE TEMP TABLE events (
    id INTEGER PRIMARY KEY,
    event_name TEXT,
    event_type TEXT,
    source_type TEXT,
    created_at TEXT,
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
        (req_id, item_id, "implementation_review", "verification", "2026-01-01T00:00:00Z"),
    )
    conn.commit()


def insert_epic_requirement(conn, *, req_id=2, epic_id=100, task_num=3):
    conn.execute(
        "INSERT INTO qa_requirements (id, epic_id, task_num, qa_kind, qa_phase, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (req_id, epic_id, task_num, "implementation_review", "verification", "2026-01-01T00:00:00Z"),
    )
    conn.commit()


def insert_deployment_requirement(conn, *, req_id=3, run_id="run-abc-001"):
    conn.execute(
        "INSERT INTO qa_requirements (id, deployment_run_id, qa_kind, qa_phase, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (req_id, run_id, "smoke", "post_deploy", "2026-01-01T00:00:00Z"),
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
