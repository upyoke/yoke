"""Path-integrity table DDL.

Owns the four ``path_integrity_*`` tables that record the verifier's
runs, failures, repairs, and named regression fixtures. Consumed by
the schema_init pipeline (fresh installs) so a new Yoke DB has the
tables on first boot. ``create_path_integrity_tables`` is the single
DDL surface.

The four tables together represent substrate truth about path identity,
continuity, verifier runs, and verifier failures. They are shadow-mode
reporting only: no other Yoke workflow blocks on these rows in this
slice. The single sanctioned blocking consumer is the
:func:`yoke_core.domain.path_integrity.has_green_run` helper, which
future path-integrity consumers will read.

Schema layering rules:

* ``path_integrity_runs``: one row per verifier invocation. Captures
  ``status``, ``commit_sha``, and structured ``skip_reason`` /
  ``block_reason`` / ``abort_reason`` columns. Status vocabulary:
  ``running`` (in flight), ``passed`` / ``failed`` (completed),
  ``skipped`` / ``blocked`` (could not run, no failures recorded),
  ``aborted`` (closed-out stale ``running`` row from a prior crash).
* ``path_integrity_failures``: one row per invariant failure inside a
  run. ``invariant_kind`` is the named invariant; ``details`` is JSON
  payload (kept as TEXT for portability and JSONB upgrade later).
  Repair status (``open`` / ``repaired`` / ``abandoned``) tracks whether
  the failure is still actionable.
* ``path_integrity_repairs``: one row per repair attempt against a
  specific failure. ``status`` walks ``preparing -> applied`` on success
  or ``preparing -> failed`` on exception. The ``preparing`` row is
  written BEFORE substrate mutation so a crashed repair leaves an
  audit-visible trace.
* ``path_integrity_fixtures``: one row per named regression fixture. The
  fixture loader records its name and the substrate state it produces;
  tests assert that loading a known-bad fixture causes the expected
  invariant to fail deterministically.

The tables are additive. They do not rewrite existing path substrate
rows during apply. They reference ``path_targets`` and ``path_snapshots``
by ID with ON DELETE NO ACTION (the verifier reads the substrate, it
does not own its lifecycle) and reference ``events.event_id`` for
provenance on repair rows.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


def create_path_integrity_tables(conn: Any) -> None:
    """Create the path-integrity tables and indexes (idempotent)."""
    execute_schema_script(conn, """
        CREATE TABLE IF NOT EXISTS path_integrity_runs (
            id INTEGER PRIMARY KEY,
            project_id INTEGER REFERENCES projects(id),
            commit_sha TEXT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            skip_reason TEXT,
            block_reason TEXT,
            abort_reason TEXT,
            failure_count INTEGER NOT NULL DEFAULT 0,
            unrepaired_failure_count INTEGER NOT NULL DEFAULT 0,
            verifier_version TEXT NOT NULL DEFAULT 'v1'
        );
        CREATE INDEX IF NOT EXISTS idx_path_integrity_runs_project
            ON path_integrity_runs(project_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_path_integrity_runs_status
            ON path_integrity_runs(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_path_integrity_runs_commit
            ON path_integrity_runs(project_id, commit_sha, status);
        CREATE TABLE IF NOT EXISTS path_integrity_failures (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            invariant_kind TEXT NOT NULL,
            target_id INTEGER,
            details TEXT NOT NULL DEFAULT '{}',
            repair_status TEXT NOT NULL DEFAULT 'open',
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES path_integrity_runs(id),
            FOREIGN KEY (target_id) REFERENCES path_targets(id)
        );
        CREATE INDEX IF NOT EXISTS idx_path_integrity_failures_run
            ON path_integrity_failures(run_id);
        CREATE INDEX IF NOT EXISTS idx_path_integrity_failures_open
            ON path_integrity_failures(repair_status, run_id);
        CREATE TABLE IF NOT EXISTS path_integrity_repairs (
            id INTEGER PRIMARY KEY,
            failure_id INTEGER NOT NULL,
            operation TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            applied_at TEXT,
            error_text TEXT,
            arguments TEXT NOT NULL DEFAULT '{}',
            -- opaque provenance string; deliberately NOT an FK into the
            -- retention-pruned events ledger (decision record:
            -- docs/archive/decisions/path-provenance-event-fk.md)
            recorded_event_id TEXT,
            abandon_reason TEXT,
            FOREIGN KEY (failure_id) REFERENCES path_integrity_failures(id)
        );
        CREATE INDEX IF NOT EXISTS idx_path_integrity_repairs_failure
            ON path_integrity_repairs(failure_id);
        CREATE INDEX IF NOT EXISTS idx_path_integrity_repairs_status
            ON path_integrity_repairs(status);
        CREATE TABLE IF NOT EXISTS path_integrity_fixtures (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            seeded_at TEXT NOT NULL,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            expected_invariant_kind TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_path_integrity_fixtures_project
            ON path_integrity_fixtures(project_id);
    """)
    conn.commit()


__all__ = ["create_path_integrity_tables"]
