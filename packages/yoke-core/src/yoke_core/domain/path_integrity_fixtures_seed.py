"""Per-fixture seed implementations for the path-integrity harness.

Each function in this module materializes one named fixture's
substrate state into a database connection and writes the matching
``path_integrity_fixtures`` row. Shared helpers live in
:mod:`yoke_core.domain.path_integrity_fixtures_helpers`. The public
catalog and loader live in :mod:`yoke_core.domain.path_integrity_fixtures`
— that module is the only sanctioned import path for callers.

The ``broken_snapshot_idempotency_v1`` fixture additionally drops the
``UNIQUE(project_id, commit_sha)`` constraint on ``path_snapshots`` so
the duplicate-snapshot case the verifier must catch can be
materialized.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.path_integrity_fixtures_helpers import (
    KIND_DIRECTORY,
    KIND_FILE,
    ROOT,
    _p,
    ensure_project_row,
    mint_snapshot,
    mint_target,
    record_fixture_row,
)
from yoke_core.domain.path_integrity_invariants import (
    INVARIANT_CONTEXT_INHERITANCE,
    INVARIANT_CONTINUITY_DETERMINISM,
    INVARIANT_DRIFT,
    INVARIANT_DUPLICATE_IDENTITY,
    INVARIANT_PARENT_CHILD,
    INVARIANT_SNAPSHOT_IDEMPOTENCY,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


def fixture_clean_v1(
    conn: Any, project_id: str = "fix_clean"
) -> int:
    ensure_project_row(conn, project_id)
    root_id = mint_target(
        conn, project_id=project_id, path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    file_a = mint_target(
        conn, project_id=project_id, path_string="a.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitclean",
        target_ids=(root_id, file_a),
    )
    return record_fixture_row(
        conn,
        name="clean_v1",
        description="Minimal coherent substrate (one root, one file, "
                    "one snapshot). Verifier must pass.",
        project_id=project_id,
        expected_invariant_kind=None,
    )


def fixture_duplicate_identity_v1(
    conn: Any, project_id: str = "fix_dupe"
) -> int:
    ensure_project_row(conn, project_id)
    root_id = mint_target(
        conn, project_id=project_id, path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    conn.execute("DROP INDEX IF EXISTS uq_path_targets_generation")
    a1 = mint_target(
        conn, project_id=project_id, path_string="dup.txt",
        kind=KIND_FILE, parent_target_id=root_id, generation=1,
    )
    a2 = mint_target(
        conn, project_id=project_id, path_string="dup.txt",
        kind=KIND_FILE, parent_target_id=root_id, generation=1,
    )
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitdupe",
        target_ids=(root_id, a1, a2),
    )
    return record_fixture_row(
        conn,
        name="duplicate_identity_v1",
        description="Two path_targets rows share "
                    "(project_id, path_string, generation).",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_DUPLICATE_IDENTITY,
    )


def fixture_incoherent_parent_child_v1(
    conn: Any, project_id: str = "fix_pc"
) -> int:
    ensure_project_row(conn, project_id)
    ensure_project_row(conn, "fix_pc_other")
    other_root = mint_target(
        conn, project_id="fix_pc_other", path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    root_id = mint_target(
        conn, project_id=project_id, path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    bad_child = mint_target(
        conn, project_id=project_id, path_string="cross.txt",
        kind=KIND_FILE, parent_target_id=other_root,
    )
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitcrossparent",
        target_ids=(root_id, bad_child),
    )
    return record_fixture_row(
        conn,
        name="incoherent_parent_child_v1",
        description="path_targets.parent_target_id references a row "
                    "in a different project.",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_PARENT_CHILD,
    )


def fixture_broken_snapshot_idempotency_v1(
    conn: Any, project_id: str = "fix_idem"
) -> int:
    ensure_project_row(conn, project_id)
    root_id = mint_target(
        conn, project_id=project_id, path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    file_a = mint_target(
        conn, project_id=project_id, path_string="a.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    file_b = mint_target(
        conn, project_id=project_id, path_string="b.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "ALTER TABLE path_snapshots DROP CONSTRAINT IF EXISTS "
            "path_snapshots_project_id_commit_sha_key"
        )
    else:
        execute_schema_script(conn, """
            CREATE TABLE path_snapshots__tmp (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                commit_sha TEXT NOT NULL,
                built_at TEXT NOT NULL
            );
            INSERT INTO path_snapshots__tmp
            SELECT id, project_id, commit_sha, built_at FROM path_snapshots;
            DROP TABLE path_snapshots;
            ALTER TABLE path_snapshots__tmp RENAME TO path_snapshots;
        """)
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitidem",
        target_ids=(root_id, file_a),
    )
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitidem",
        target_ids=(root_id, file_a, file_b),
    )
    return record_fixture_row(
        conn,
        name="broken_snapshot_idempotency_v1",
        description="Two path_snapshots rows for the same "
                    "(project_id, commit_sha) disagree on entry set.",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_SNAPSHOT_IDEMPOTENCY,
    )


def fixture_ambiguous_continuity_v1(
    conn: Any, project_id: str = "fix_cont"
) -> int:
    ensure_project_row(conn, project_id)
    root_id = mint_target(
        conn, project_id=project_id, path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    before = mint_target(
        conn, project_id=project_id, path_string="old.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    after_a = mint_target(
        conn, project_id=project_id, path_string="new_a.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    after_b = mint_target(
        conn, project_id=project_id, path_string="new_b.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    p = _p(conn)
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before, after_a, "evt-ambig-a", iso8601_now()),
    )
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before, after_b, "evt-ambig-b", iso8601_now()),
    )
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitcont",
        target_ids=(root_id, before, after_a, after_b),
    )
    return record_fixture_row(
        conn,
        name="ambiguous_continuity_v1",
        description="Two path_moves rows for the same before_target "
                    "point to different after_targets with no "
                    "more-specific edge.",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_CONTINUITY_DETERMINISM,
    )


def fixture_conflicting_context_inheritance_v1(
    conn: Any, project_id: str = "fix_ctx"
) -> int:
    ensure_project_row(conn, project_id)
    root_id = mint_target(
        conn, project_id=project_id, path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    before_a = mint_target(
        conn, project_id=project_id, path_string="old_a.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    before_b = mint_target(
        conn, project_id=project_id, path_string="old_b.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    after = mint_target(
        conn, project_id=project_id, path_string="new.txt",
        kind=KIND_FILE, parent_target_id=root_id,
    )
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitctx",
        target_ids=(root_id, before_a, before_b, after),
    )
    p = _p(conn)
    conn.execute(
        "INSERT INTO path_context_values "
        "(target_id, context_family, entry_key, value, "
        " recorded_event_id, recorded_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
        (before_a, "posture", "criticality",
         '{"value":"high"}', "evt-ctx-a", iso8601_now()),
    )
    conn.execute(
        "INSERT INTO path_context_values "
        "(target_id, context_family, entry_key, value, "
        " recorded_event_id, recorded_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
        (before_b, "posture", "criticality",
         '{"value":"low"}', "evt-ctx-b", iso8601_now()),
    )
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before_a, after, "evt-ctx-a", iso8601_now()),
    )
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before_b, after, "evt-ctx-b", iso8601_now()),
    )
    return record_fixture_row(
        conn,
        name="conflicting_context_inheritance_v1",
        description="Two continuity sources project conflicting "
                    "path_context_values onto one after-target.",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_CONTEXT_INHERITANCE,
    )


def fixture_substrate_drift_v1(
    conn: Any, project_id: str = "fix_drift"
) -> int:
    ensure_project_row(conn, project_id)
    ensure_project_row(conn, "fix_drift_other")
    root_id = mint_target(
        conn, project_id=project_id, path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    other_root = mint_target(
        conn, project_id="fix_drift_other", path_string=ROOT,
        kind=KIND_DIRECTORY, parent_target_id=None,
    )
    other_file = mint_target(
        conn, project_id="fix_drift_other", path_string="foreign.txt",
        kind=KIND_FILE, parent_target_id=other_root,
    )
    mint_snapshot(
        conn, project_id=project_id, commit_sha="commitdrift",
        target_ids=(root_id, other_file),
    )
    return record_fixture_row(
        conn,
        name="substrate_drift_v1",
        description="A project snapshot entry references a path_target "
                    "owned by a different project.",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_DRIFT,
    )


__all__ = [
    "fixture_ambiguous_continuity_v1",
    "fixture_broken_snapshot_idempotency_v1",
    "fixture_clean_v1",
    "fixture_conflicting_context_inheritance_v1",
    "fixture_duplicate_identity_v1",
    "fixture_incoherent_parent_child_v1",
    "fixture_substrate_drift_v1",
]
