"""Path-registry table DDL split out of schema_init_tables.

Owns the path-substrate DDL: the path registry identity layer ``path_targets`` /
``path_snapshots`` / ``path_snapshot_entries`` trio plus the path continuity layer
``path_moves`` / ``path_context_values`` recording surfaces.

Imported by both the schema_init pipeline (fresh installs) and the
one-shot migration module (existing authoritative DBs) so the DDL
lives in exactly one place. ``create_path_registry_tables`` is the
sole public surface.

``path_moves`` records authored continuity edges between two
``path_targets`` rows. Provenance is the ``events.event_id`` of the
workflow-observed or operator-adjudicated event that authorized the
record. Heuristic-only rename detection is forbidden at the writer
layer; the table itself just stores the references.

``path_context_values`` attaches family-keyed durable operating truth
to ``path_targets``. ``context_family`` opens with ``posture`` and
``doc_link`` (per the path continuity layer cutover from Project Structure) and expands
as future consumers declare new families. ``entry_key`` is the
keyed-set key for keyed families and the empty-string sentinel for
singleton families. ``value`` is JSON-shaped TEXT today and migrates
cleanly to JSONB on Postgres.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_path_registry_tables(conn: Any) -> None:
    """Create the path-registry substrate tables and indexes (idempotent)."""
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS path_targets (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            kind TEXT NOT NULL,
            path_string TEXT NOT NULL,
            generation INTEGER NOT NULL,
            parent_target_id INTEGER,
            created_at TEXT NOT NULL,
            materialization_state TEXT NOT NULL DEFAULT 'observed'
                CHECK(materialization_state IN (
                    'planned','observed','abandoned','tentative'
                )),
            materialization_updated_at TEXT,
            planned_by_item_id INTEGER,
            planned_by_claim_id INTEGER,
            FOREIGN KEY (parent_target_id) REFERENCES path_targets(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_path_targets_generation
            ON path_targets(project_id, path_string, generation);
        CREATE INDEX IF NOT EXISTS idx_path_targets_lookup
            ON path_targets(project_id, path_string);
        CREATE INDEX IF NOT EXISTS idx_path_targets_parent
            ON path_targets(parent_target_id);
        CREATE INDEX IF NOT EXISTS idx_path_targets_materialization
            ON path_targets(project_id, materialization_state);
        CREATE INDEX IF NOT EXISTS idx_path_targets_planned_item
            ON path_targets(planned_by_item_id)
            WHERE planned_by_item_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS path_snapshots (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            commit_sha TEXT NOT NULL,
            built_at TEXT NOT NULL,
            UNIQUE(project_id, commit_sha)
        );
        CREATE TABLE IF NOT EXISTS path_snapshot_entries (
            snapshot_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            line_count INTEGER,
            language TEXT,
            module_name TEXT,
            area TEXT,
            is_generated INTEGER NOT NULL DEFAULT 0,
            dependency_edges TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (snapshot_id, target_id),
            FOREIGN KEY (snapshot_id) REFERENCES path_snapshots(id),
            FOREIGN KEY (target_id) REFERENCES path_targets(id)
        );
        CREATE INDEX IF NOT EXISTS idx_path_snapshot_entries_target
            ON path_snapshot_entries(target_id);
        CREATE TABLE IF NOT EXISTS path_snapshot_symlink_facts (
            snapshot_id INTEGER NOT NULL,
            symlink_path TEXT NOT NULL,
            symlink_target_id INTEGER,
            reason TEXT NOT NULL,
            target_attempt TEXT,
            canonical_path TEXT,
            canonical_target_id INTEGER,
            PRIMARY KEY (snapshot_id, symlink_path),
            FOREIGN KEY (snapshot_id) REFERENCES path_snapshots(id),
            FOREIGN KEY (symlink_target_id) REFERENCES path_targets(id),
            FOREIGN KEY (canonical_target_id) REFERENCES path_targets(id)
        );
        CREATE INDEX IF NOT EXISTS idx_path_snapshot_symlink_targets
            ON path_snapshot_symlink_facts(
                symlink_target_id, canonical_target_id
            );
        CREATE TABLE IF NOT EXISTS path_moves (
            id INTEGER PRIMARY KEY,
            before_target_id INTEGER NOT NULL,
            after_target_id INTEGER NOT NULL,
            -- opaque provenance string; deliberately NOT an FK into the
            -- retention-pruned events ledger (decision record:
            -- docs/archive/decisions/path-provenance-event-fk.md)
            recorded_event_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (before_target_id) REFERENCES path_targets(id),
            FOREIGN KEY (after_target_id) REFERENCES path_targets(id)
        );
        CREATE INDEX IF NOT EXISTS idx_path_moves_before
            ON path_moves(before_target_id);
        CREATE INDEX IF NOT EXISTS idx_path_moves_after
            ON path_moves(after_target_id);
        CREATE TABLE IF NOT EXISTS path_context_values (
            id INTEGER PRIMARY KEY,
            target_id INTEGER NOT NULL,
            context_family TEXT NOT NULL,
            entry_key TEXT NOT NULL DEFAULT '',
            value TEXT NOT NULL DEFAULT '{}',  -- JSONB on Postgres
            -- opaque provenance string (see path_moves note above)
            recorded_event_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            UNIQUE(target_id, context_family, entry_key),
            FOREIGN KEY (target_id) REFERENCES path_targets(id)
        );
        CREATE INDEX IF NOT EXISTS idx_path_context_values_target
            ON path_context_values(target_id);
        CREATE INDEX IF NOT EXISTS idx_path_context_values_family
            ON path_context_values(target_id, context_family);
    """)
    create_path_snapshot_sync_upload_tables(conn)


def create_path_snapshot_sync_upload_tables(conn: Any) -> None:
    """Create staging tables for chunked project snapshot uploads."""
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS path_snapshot_sync_uploads (
            upload_id TEXT PRIMARY KEY,
            project_ref TEXT NOT NULL,
            repo_root TEXT,
            ref TEXT NOT NULL,
            commit_sha TEXT NOT NULL,
            expected_file_count INTEGER NOT NULL,
            expected_chunk_count INTEGER NOT NULL,
            warnings_json TEXT NOT NULL,
            symlinks_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS path_snapshot_sync_upload_chunks (
            upload_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            files_json TEXT NOT NULL,
            PRIMARY KEY (upload_id, chunk_index)
        );
    """)
    conn.commit()


__all__ = [
    "create_path_registry_tables",
    "create_path_snapshot_sync_upload_tables",
]
