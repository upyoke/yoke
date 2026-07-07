"""Schema initialization for shepherd-owned tables."""
from __future__ import annotations

from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.schema_init_apply import execute_schema_script

_INIT_SQL = """\
CREATE TABLE IF NOT EXISTS shepherd_verdicts (
    id INTEGER PRIMARY KEY,
    item TEXT NOT NULL,
    transition TEXT NOT NULL,
    worker TEXT NOT NULL,
    verdict TEXT NOT NULL,
    caveats TEXT,
    attempt INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS caveat_dispositions (
    id INTEGER PRIMARY KEY,
    item TEXT NOT NULL,
    transition TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    caveat_num INTEGER NOT NULL,
    caveat_text TEXT NOT NULL,
    disposition TEXT NOT NULL,
    resolution_details TEXT,
    verdict_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (verdict_id) REFERENCES shepherd_verdicts(id),
    UNIQUE(item, transition, attempt, caveat_num)
);
CREATE INDEX IF NOT EXISTS idx_cd_item ON caveat_dispositions(item);

CREATE TABLE IF NOT EXISTS item_dependencies (
    id INTEGER PRIMARY KEY,
    dependent_item TEXT NOT NULL,
    blocking_item TEXT NOT NULL,
    gate_point TEXT NOT NULL DEFAULT 'activation',
    satisfaction TEXT NOT NULL DEFAULT 'status:done',
    source TEXT NOT NULL,
    session_id INTEGER,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(dependent_item, blocking_item, gate_point)
);
CREATE INDEX IF NOT EXISTS idx_id_dependent ON item_dependencies(dependent_item);
CREATE INDEX IF NOT EXISTS idx_id_blocking ON item_dependencies(blocking_item);
"""


def _ensure_dependency_metadata_columns(conn) -> None:
    for col, default in [("rationale", "''"), ("evidence_json", "'{}'")]:
        if _column_exists(conn, "item_dependencies", col):
            continue
        try:
            conn.execute(
                f"ALTER TABLE item_dependencies ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
            )
        except Exception:
            pass


def cmd_init(conn) -> str:
    execute_schema_script(conn, _INIT_SQL)
    _ensure_dependency_metadata_columns(conn)
    conn.commit()
    return "Shepherd tables initialized"
