"""Shepherd-owned tables: verdicts, caveat dispositions and item dependencies.

Schema convergence (:mod:`yoke_core.domain.schema_creation`) is the only
caller, so every database that boots carries these tables.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists, _column_exists
from yoke_core.domain.schema_init_apply import execute_schema_script

_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS shepherd_verdicts (
    id INTEGER PRIMARY KEY,
    public_ref TEXT,
    archived_item_key TEXT,
    transition TEXT NOT NULL,
    worker TEXT NOT NULL,
    verdict TEXT NOT NULL,
    caveats TEXT,
    attempt INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS caveat_dispositions (
    id INTEGER PRIMARY KEY,
    public_ref TEXT,
    archived_item_key TEXT,
    transition TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    caveat_num INTEGER NOT NULL,
    caveat_text TEXT NOT NULL,
    disposition TEXT NOT NULL,
    resolution_details TEXT,
    verdict_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (verdict_id) REFERENCES shepherd_verdicts(id),
    UNIQUE(public_ref, transition, attempt, caveat_num)
);

CREATE TABLE IF NOT EXISTS item_dependencies (
    id INTEGER PRIMARY KEY,
    dependent_item_id INTEGER NOT NULL REFERENCES items(id),
    blocking_item_id INTEGER NOT NULL REFERENCES items(id),
    gate_point TEXT NOT NULL DEFAULT 'activation',
    satisfaction TEXT NOT NULL DEFAULT 'status:done',
    source TEXT NOT NULL,
    session_id TEXT,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(dependent_item_id, blocking_item_id, gate_point)
);
CREATE INDEX IF NOT EXISTS idx_id_dependent ON item_dependencies(dependent_item_id);
CREATE INDEX IF NOT EXISTS idx_id_blocking ON item_dependencies(blocking_item_id);
"""


def create_shepherd_tables(conn: Any) -> None:
    """Create the shepherd tables, their indexes and additive columns.

    ``item_dependencies`` references ``items``, so this runs after the core
    tables in dependency order.
    """
    execute_schema_script(conn, _CREATE_SQL)
    if _column_exists(conn, "caveat_dispositions", "public_ref"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cd_item ON caveat_dispositions(public_ref)"
        )
    for column, default in (("rationale", "''"), ("evidence_json", "'{}'")):
        _add_column_if_not_exists(
            conn, "item_dependencies", column, f"TEXT NOT NULL DEFAULT {default}"
        )
    conn.commit()
