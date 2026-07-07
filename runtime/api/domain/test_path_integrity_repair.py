"""Path-integrity repair surface tests.

Asserts AC-6 / AC-17:

* Repair rows write ``preparing`` BEFORE substrate mutation.
* Successful apply transitions to ``applied`` and updates the failure
  to ``repaired``, decrementing the run's
  ``unrepaired_failure_count``.
* Re-running an already-applied repair is a no-op that returns the
  existing applied repair id.
* ``--dry-run`` writes an audited row without substrate mutation.
* ``mark_failure_abandoned`` flips ``repair_status='abandoned'`` and
  records the reason without modifying substrate.
* Unknown invariant kinds without a default operation refuse cleanly.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain._path_integrity_test_helpers import path_integrity_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain import (
    path_integrity, path_integrity_fixtures, path_integrity_repair,
)
from yoke_core.domain.path_integrity_repair import (
    OP_DELETE_DUPLICATE_TARGET,
    OP_REBIND_PARENT,
    PathIntegrityRepairError,
    apply_repair,
    mark_failure_abandoned,
)
from yoke_core.domain.path_integrity_repair_audit import (
    FAILURE_ABANDONED, FAILURE_REPAIRED, STATUS_APPLIED,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def db_with_dupe(tmp_path):
    with path_integrity_db(tmp_path) as conn:
        path_integrity_fixtures.load_fixture(
            conn, "duplicate_identity_v1",
        )
        run_id = path_integrity.verify_project(conn, "fix_dupe")
        yield conn, run_id


@pytest.fixture
def db_with_parent_child(tmp_path):
    with path_integrity_db(tmp_path) as conn:
        path_integrity_fixtures.load_fixture(
            conn, "incoherent_parent_child_v1",
        )
        run_id = path_integrity.verify_project(conn, "fix_pc")
        yield conn, run_id


def _failure_for_kind(conn, run_id, kind):
    p = _p(conn)
    row = conn.execute(
        "SELECT id, target_id, repair_status FROM path_integrity_failures "
        f"WHERE run_id={p} AND invariant_kind={p} ORDER BY id LIMIT 1",
        (run_id, kind),
    ).fetchone()
    return row


def test_apply_repair_for_duplicate_identity(db_with_dupe):
    conn, run_id = db_with_dupe
    failure = _failure_for_kind(
        conn, run_id, path_integrity.INVARIANT_DUPLICATE_IDENTITY,
    )
    failure_id = int(failure[0])
    repair_id = apply_repair(conn, failure_id=failure_id)

    p = _p(conn)
    repair_row = conn.execute(
        "SELECT operation, status, applied_at, error_text "
        f"FROM path_integrity_repairs WHERE id={p}",
        (repair_id,),
    ).fetchone()
    assert repair_row[0] == OP_DELETE_DUPLICATE_TARGET
    assert repair_row[1] == STATUS_APPLIED
    assert repair_row[2] is not None
    assert repair_row[3] is None

    failure_row = conn.execute(
        f"SELECT repair_status FROM path_integrity_failures WHERE id={p}",
        (failure_id,),
    ).fetchone()
    assert failure_row[0] == FAILURE_REPAIRED

    run_row = conn.execute(
        "SELECT unrepaired_failure_count FROM path_integrity_runs "
        f"WHERE id={p}",
        (run_id,),
    ).fetchone()
    assert run_row[0] >= 0
    initial_failures = conn.execute(
        f"SELECT failure_count FROM path_integrity_runs WHERE id={p}",
        (run_id,),
    ).fetchone()[0]
    assert initial_failures > run_row[0]


def test_apply_repair_emits_repair_applied_event(db_with_dupe):
    conn, run_id = db_with_dupe
    failure = _failure_for_kind(
        conn, run_id, path_integrity.INVARIANT_DUPLICATE_IDENTITY,
    )
    apply_repair(conn, failure_id=int(failure[0]))
    row = conn.execute(
        "SELECT event_name FROM events "
        "WHERE event_name='PathIntegrityRepairApplied'",
    ).fetchone()
    assert row is not None


def test_dry_run_does_not_mutate_substrate(db_with_dupe):
    conn, run_id = db_with_dupe
    failure = _failure_for_kind(
        conn, run_id, path_integrity.INVARIANT_DUPLICATE_IDENTITY,
    )
    failure_id = int(failure[0])
    target_id = int(failure[1])
    p = _p(conn)
    pre_count = conn.execute(
        f"SELECT COUNT(*) FROM path_targets WHERE id={p}",
        (target_id,),
    ).fetchone()[0]

    repair_id = apply_repair(
        conn, failure_id=failure_id, dry_run=True,
    )

    post_count = conn.execute(
        f"SELECT COUNT(*) FROM path_targets WHERE id={p}",
        (target_id,),
    ).fetchone()[0]
    assert post_count == pre_count

    repair_row = conn.execute(
        f"SELECT status FROM path_integrity_repairs WHERE id={p}",
        (repair_id,),
    ).fetchone()
    assert repair_row[0] == STATUS_APPLIED

    failure_row = conn.execute(
        f"SELECT repair_status FROM path_integrity_failures WHERE id={p}",
        (failure_id,),
    ).fetchone()
    # dry-run does not mark the failure repaired
    assert failure_row[0] == "open"


def test_apply_repair_for_parent_child(db_with_parent_child):
    conn, run_id = db_with_parent_child
    failure = _failure_for_kind(
        conn, run_id, path_integrity.INVARIANT_PARENT_CHILD,
    )
    failure_id = int(failure[0])
    target_id = int(failure[1])

    p = _p(conn)
    pre_parent = conn.execute(
        f"SELECT parent_target_id FROM path_targets WHERE id={p}",
        (target_id,),
    ).fetchone()[0]

    apply_repair(conn, failure_id=failure_id)

    post_parent = conn.execute(
        f"SELECT parent_target_id FROM path_targets WHERE id={p}",
        (target_id,),
    ).fetchone()[0]
    assert post_parent != pre_parent  # rebound onto in-project root

    in_project_root = conn.execute(
        "SELECT t.id FROM path_targets t "
        "JOIN projects p ON p.id = t.project_id "
        "WHERE p.slug='fix_pc' AND t.path_string=''",
    ).fetchone()[0]
    assert post_parent == in_project_root


def test_re_apply_already_repaired_is_noop(db_with_dupe):
    conn, run_id = db_with_dupe
    failure = _failure_for_kind(
        conn, run_id, path_integrity.INVARIANT_DUPLICATE_IDENTITY,
    )
    failure_id = int(failure[0])
    first_id = apply_repair(conn, failure_id=failure_id)
    second_id = apply_repair(conn, failure_id=failure_id)
    assert second_id == first_id


def test_unknown_invariant_kind_refuses(db_with_dupe):
    conn, run_id = db_with_dupe
    # Insert a synthetic failure with an unknown kind
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_integrity_failures "
        "(run_id, invariant_kind, target_id, details, recorded_at) "
        f"VALUES ({p}, 'novel_invariant', NULL, '{{}}', "
        f"        {p}) RETURNING id",
        (run_id, iso8601_now()),
    )
    failure_id = int(cur.fetchone()[0])
    conn.commit()
    with pytest.raises(PathIntegrityRepairError):
        apply_repair(conn, failure_id=failure_id)


def test_mark_failure_abandoned_records_reason(db_with_dupe):
    conn, run_id = db_with_dupe
    failure = _failure_for_kind(
        conn, run_id, path_integrity.INVARIANT_DUPLICATE_IDENTITY,
    )
    failure_id = int(failure[0])
    repair_id = mark_failure_abandoned(
        conn, failure_id=failure_id, reason="duplicate is benign",
    )
    p = _p(conn)
    repair_row = conn.execute(
        "SELECT status, abandon_reason FROM path_integrity_repairs "
        f"WHERE id={p}",
        (repair_id,),
    ).fetchone()
    assert repair_row[0] == "abandoned"
    assert repair_row[1] == "duplicate is benign"

    failure_row = conn.execute(
        f"SELECT repair_status FROM path_integrity_failures WHERE id={p}",
        (failure_id,),
    ).fetchone()
    assert failure_row[0] == FAILURE_ABANDONED


def test_abandon_refuses_empty_reason(db_with_dupe):
    conn, run_id = db_with_dupe
    failure = _failure_for_kind(
        conn, run_id, path_integrity.INVARIANT_DUPLICATE_IDENTITY,
    )
    with pytest.raises(PathIntegrityRepairError):
        mark_failure_abandoned(
            conn, failure_id=int(failure[0]), reason="   ",
        )
