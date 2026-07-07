"""Path-integrity verifier tests.

Covers the six invariants on synthetic substrate, run lifecycle
transitions, crash-recovery semantics, the ``has_green_run`` helper,
and the per-commit ``--commit`` resolution that AC-16 requires.

Fixture-loader behavior lives in ``test_path_integrity_fixtures.py``
and live-project coverage lives in ``test_path_integrity_live.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import path_integrity, path_integrity_fixtures
from yoke_core.domain._path_integrity_test_helpers import path_integrity_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.path_integrity_fixtures_helpers import project_row_id
from yoke_core.domain.path_integrity_runs import (
    SKIP_NO_HEAD_SNAPSHOT,
    SKIP_NO_PROJECT,
    SKIP_NO_SUBSTRATE,
    STATUS_ABORTED,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_RUNNING,
    STATUS_SKIPPED,
)


@pytest.fixture
def fresh_db(tmp_path):
    with path_integrity_db(tmp_path) as conn:
        yield conn


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _run_status(conn, run_id):
    p = _p(conn)
    return conn.execute(
        "SELECT status, failure_count, unrepaired_failure_count, "
        "       skip_reason, abort_reason "
        f"FROM path_integrity_runs WHERE id={p}",
        (run_id,),
    ).fetchone()


def _failure_kinds(conn, run_id):
    p = _p(conn)
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT invariant_kind FROM path_integrity_failures "
            f"WHERE run_id={p} ORDER BY id",
            (run_id,),
        ).fetchall()
    ]


def test_clean_fixture_passes(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    run_id = path_integrity.verify_project(fresh_db, "fix_clean")
    status, fc, ufc, skip, abort = _run_status(fresh_db, run_id)
    assert status == STATUS_PASSED
    assert fc == 0
    assert ufc == 0
    assert skip is None
    assert abort is None


def test_duplicate_identity_fails(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "duplicate_identity_v1",
    )
    run_id = path_integrity.verify_project(fresh_db, "fix_dupe")
    status, fc, _, _, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_FAILED
    assert fc >= 1
    kinds = _failure_kinds(fresh_db, run_id)
    assert path_integrity.INVARIANT_DUPLICATE_IDENTITY in kinds


def test_incoherent_parent_child_fails(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "incoherent_parent_child_v1",
    )
    run_id = path_integrity.verify_project(fresh_db, "fix_pc")
    status, _, _, _, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_FAILED
    kinds = _failure_kinds(fresh_db, run_id)
    assert path_integrity.INVARIANT_PARENT_CHILD in kinds


def test_broken_snapshot_idempotency_fails(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "broken_snapshot_idempotency_v1",
    )
    run_id = path_integrity.verify_project(fresh_db, "fix_idem")
    status, _, _, _, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_FAILED
    kinds = _failure_kinds(fresh_db, run_id)
    assert path_integrity.INVARIANT_SNAPSHOT_IDEMPOTENCY in kinds


def test_ambiguous_continuity_fails(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "ambiguous_continuity_v1",
    )
    run_id = path_integrity.verify_project(fresh_db, "fix_cont")
    status, _, _, _, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_FAILED
    kinds = _failure_kinds(fresh_db, run_id)
    assert path_integrity.INVARIANT_CONTINUITY_DETERMINISM in kinds


def test_conflicting_context_inheritance_fails(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "conflicting_context_inheritance_v1",
    )
    run_id = path_integrity.verify_project(fresh_db, "fix_ctx")
    status, _, _, _, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_FAILED
    kinds = _failure_kinds(fresh_db, run_id)
    assert path_integrity.INVARIANT_CONTEXT_INHERITANCE in kinds


def test_substrate_drift_fails(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "substrate_drift_v1",
    )
    run_id = path_integrity.verify_project(fresh_db, "fix_drift")
    status, _, _, _, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_FAILED
    kinds = _failure_kinds(fresh_db, run_id)
    assert path_integrity.INVARIANT_DRIFT in kinds


def test_skip_no_project(fresh_db):
    run_id = path_integrity.verify_project(fresh_db, 99999)
    status, _, _, skip, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_SKIPPED
    assert skip == SKIP_NO_PROJECT


def test_skip_no_substrate(fresh_db):
    p = _p(fresh_db)
    fresh_db.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (998, "empty", "empty", iso8601_now()),
    )
    fresh_db.commit()
    run_id = path_integrity.verify_project(fresh_db, "empty")
    status, _, _, skip, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_SKIPPED
    assert skip == SKIP_NO_SUBSTRATE


def test_skip_no_head_snapshot_for_unknown_commit(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    run_id = path_integrity.verify_project(
        fresh_db, "fix_clean", commit_sha="never_existed",
    )
    status, _, _, skip, _ = _run_status(fresh_db, run_id)
    assert status == STATUS_SKIPPED
    assert skip == SKIP_NO_HEAD_SNAPSHOT


def test_close_stale_running_runs(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    p = _p(fresh_db)
    cur = fresh_db.execute(
        "INSERT INTO path_integrity_runs "
        "(project_id, commit_sha, status, started_at, "
        " verifier_version) "
        f"VALUES ({p}, 'older_sha', {p}, {p}, 'v1') "
        "RETURNING id",
        (project_row_id("fix_clean"), STATUS_RUNNING, iso8601_now()),
    )
    stale_id = int(cur.fetchone()[0])
    fresh_db.commit()

    path_integrity.verify_project(fresh_db, "fix_clean")
    row = fresh_db.execute(
        f"SELECT status, abort_reason FROM path_integrity_runs WHERE id={p}",
        (stale_id,),
    ).fetchone()
    assert row[0] == STATUS_ABORTED
    assert row[1] == path_integrity.ABORT_RESUMED_AFTER_CRASH


def test_has_green_run_true_after_pass(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    path_integrity.verify_project(fresh_db, "fix_clean")
    p = _p(fresh_db)
    row = fresh_db.execute(
        "SELECT commit_sha FROM path_integrity_runs "
        f"WHERE project_id={p} AND status={p}",
        (project_row_id("fix_clean"), STATUS_PASSED),
    ).fetchone()
    sha = str(row[0])
    assert path_integrity.has_green_run(fresh_db, "fix_clean", sha)


def test_has_green_run_false_for_failed_run(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "duplicate_identity_v1",
    )
    path_integrity.verify_project(fresh_db, "fix_dupe")
    p = _p(fresh_db)
    row = fresh_db.execute(
        "SELECT commit_sha FROM path_integrity_runs "
        f"WHERE project_id={p}",
        (project_row_id("fix_dupe"),),
    ).fetchone()
    sha = str(row[0])
    assert not path_integrity.has_green_run(fresh_db, "fix_dupe", sha)


def test_has_green_run_false_for_unknown_pair(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    path_integrity.verify_project(fresh_db, "fix_clean")
    assert not path_integrity.has_green_run(
        fresh_db, "fix_clean", "different_sha",
    )


def test_verify_all_projects_skips_per_project(fresh_db):
    p = _p(fresh_db)
    fresh_db.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (997, "emptyproj", "emptyproj", iso8601_now()),
    )
    fresh_db.commit()
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    run_ids = path_integrity.verify_all_projects(fresh_db)
    rows = fresh_db.execute(
        "SELECT p.slug, r.status, r.skip_reason "
        "FROM path_integrity_runs r "
        "JOIN projects p ON p.id = r.project_id "
        f"WHERE r.id IN ({','.join(p for _ in run_ids)})",
        tuple(run_ids),
    ).fetchall()
    by_slug = {str(row[0]): (str(row[1]), row[2]) for row in rows}
    assert by_slug["fix_clean"] == (STATUS_PASSED, None)
    assert by_slug["emptyproj"] == (STATUS_SKIPPED, SKIP_NO_SUBSTRATE)
    assert by_slug["yoke"] == (STATUS_SKIPPED, SKIP_NO_SUBSTRATE)


def test_per_commit_resolution_picks_named_snapshot(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    run_id_default = path_integrity.verify_project(fresh_db, "fix_clean")
    p = _p(fresh_db)
    row = fresh_db.execute(
        f"SELECT commit_sha FROM path_integrity_runs WHERE id={p}",
        (run_id_default,),
    ).fetchone()
    assert row[0] == "commitclean"

    run_id_pinned = path_integrity.verify_project(
        fresh_db, "fix_clean", commit_sha="commitclean",
    )
    row2 = fresh_db.execute(
        f"SELECT commit_sha, status FROM path_integrity_runs WHERE id={p}",
        (run_id_pinned,),
    ).fetchone()
    assert row2[0] == "commitclean"
    assert row2[1] == STATUS_PASSED


def test_run_lifecycle_emits_started_and_completed_events(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    run_id = path_integrity.verify_project(fresh_db, "fix_clean")
    rows = fresh_db.execute(
        "SELECT event_name FROM events "
        "WHERE event_name LIKE 'PathIntegrity%' "
        "ORDER BY id",
    ).fetchall()
    names = [str(r[0]) for r in rows]
    assert "PathIntegrityRunStarted" in names
    assert "PathIntegrityRunCompleted" in names
    assert run_id  # silence linter


def test_failure_emits_failure_detected_event(fresh_db):
    path_integrity_fixtures.load_fixture(
        fresh_db, "duplicate_identity_v1",
    )
    path_integrity.verify_project(fresh_db, "fix_dupe")
    rows = fresh_db.execute(
        "SELECT event_name FROM events "
        "WHERE event_name='PathIntegrityFailureDetected'",
    ).fetchall()
    assert rows
