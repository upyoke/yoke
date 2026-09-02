"""DDL for the gate-satisfier substrate: derived project facts and rung stamps.

Two additive tables carry the mechanism described in
:mod:`yoke_core.domain.gate_satisfier_ladder`:

``project_derived_facts``
    Project-scoped operating truth that nobody declared but the control
    plane can observe — whether a remote is recorded, whether a
    verification command is registered, whether environments exist, and
    what default branch the remote reports. Rows converge at every item-scoped
    ladder resolution and ``project.snapshot.sync``; each row names the
    observation that wrote it. A resolution-only project lookup can observe a
    missing row live, and the next item gate persists the same fact.

``item_gate_satisfactions``
    One row per ``(item_id, obligation)`` recording which rung of an
    item-scoped satisfier ladder actually ran. This is the durable
    answer to "was this done merged with CI, merged locally, or merely
    attested" — the question every fail-open path used to leave
    unanswerable.

Both tables are pure-additive net-new surfaces, so the boot converge
creates them and no governed migration entry is required.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_gate_satisfaction_tables(conn: Any) -> None:
    """Create the derived-fact and rung-stamp tables (idempotent)."""
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS project_derived_facts (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            fact_key TEXT NOT NULL,
            present INTEGER NOT NULL DEFAULT 0,
            fact_value TEXT NOT NULL DEFAULT '',
            observed_at TEXT NOT NULL,
            observed_from TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_project_derived_facts_key
            ON project_derived_facts(project_id, fact_key);
        CREATE TABLE IF NOT EXISTS item_gate_satisfactions (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items(id),
            obligation TEXT NOT NULL,
            rung_id TEXT NOT NULL,
            target_status TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            facts TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL,
            recorded_by_session_id TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_item_gate_satisfactions_obligation
            ON item_gate_satisfactions(item_id, obligation);
    """,
    )


__all__ = ["create_gate_satisfaction_tables"]
