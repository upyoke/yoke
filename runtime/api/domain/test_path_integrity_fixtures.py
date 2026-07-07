"""Path-integrity fixture loader tests.

Asserts that:

* every advertised fixture name actually loads,
* the loader raises ``KeyError`` for unknown names,
* each known-bad fixture trips the invariant it advertises in
  ``path_integrity_fixtures.expected_invariant_kind`` (this is the
  contract behind AC-1),
* the catalog is sorted (so ``available_fixtures`` is byte-stable).
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import path_integrity, path_integrity_fixtures
from yoke_core.domain._path_integrity_test_helpers import path_integrity_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.path_integrity_fixtures_helpers import project_row_id


@pytest.fixture
def fresh_db(tmp_path):
    with path_integrity_db(tmp_path) as conn:
        yield conn


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def test_catalog_is_sorted_and_complete():
    catalog = path_integrity_fixtures.available_fixtures()
    assert sorted(catalog) == list(catalog)
    expected = {
        "ambiguous_continuity_v1",
        "broken_snapshot_idempotency_v1",
        "clean_v1",
        "conflicting_context_inheritance_v1",
        "duplicate_identity_v1",
        "incoherent_parent_child_v1",
        "substrate_drift_v1",
    }
    assert set(catalog) == expected


def test_loader_raises_on_unknown_name(fresh_db):
    with pytest.raises(KeyError):
        path_integrity_fixtures.load_fixture(fresh_db, "no_such_fixture")


@pytest.mark.parametrize(
    "name,project_id,expected_invariant",
    [
        ("clean_v1", "fix_clean", None),
        ("duplicate_identity_v1", "fix_dupe",
            path_integrity.INVARIANT_DUPLICATE_IDENTITY),
        ("incoherent_parent_child_v1", "fix_pc",
            path_integrity.INVARIANT_PARENT_CHILD),
        ("broken_snapshot_idempotency_v1", "fix_idem",
            path_integrity.INVARIANT_SNAPSHOT_IDEMPOTENCY),
        ("ambiguous_continuity_v1", "fix_cont",
            path_integrity.INVARIANT_CONTINUITY_DETERMINISM),
        ("conflicting_context_inheritance_v1", "fix_ctx",
            path_integrity.INVARIANT_CONTEXT_INHERITANCE),
        ("substrate_drift_v1", "fix_drift",
            path_integrity.INVARIANT_DRIFT),
    ],
)
def test_fixture_records_expected_invariant(
    fresh_db, name, project_id, expected_invariant,
):
    fixture_id = path_integrity_fixtures.load_fixture(fresh_db, name)
    p = _p(fresh_db)
    row = fresh_db.execute(
        "SELECT name, project_id, expected_invariant_kind "
        f"FROM path_integrity_fixtures WHERE id={p}",
        (fixture_id,),
    ).fetchone()
    assert row[0] == name
    assert row[1] == project_row_id(project_id)
    assert row[2] == expected_invariant


def test_known_bad_fixtures_trip_named_invariant(tmp_path):
    """For each fixture with a non-null expected invariant, loading
    the fixture and running the verifier produces at least one failure
    of that invariant kind. AC-1.

    We load each known-bad fixture in isolation against a fresh DB so
    cross-fixture interactions (the snapshot-idempotency fixture
    drops the unique index) cannot contaminate the assertion.
    """
    for name in path_integrity_fixtures.available_fixtures():
        # idempotency fixture mutates schema; clean per-fixture DB.
        fixture_tmp = tmp_path / name
        fixture_tmp.mkdir()
        with path_integrity_db(fixture_tmp) as conn:
            row = conn.execute(
                "SELECT 0"
            )  # warm up
            del row
            project_id = (
                path_integrity_fixtures._DEFAULT_PROJECT_IDS[name]
            )
            path_integrity_fixtures.load_fixture(conn, name)
            run_id = path_integrity.verify_project(conn, project_id)
            p = _p(conn)
            row = conn.execute(
                "SELECT expected_invariant_kind "
                "FROM path_integrity_fixtures "
                f"WHERE name={p} ORDER BY id DESC LIMIT 1",
                (name,),
            ).fetchone()
            expected = row[0]
            failure_kinds = {
                str(r[0])
                for r in conn.execute(
                    "SELECT invariant_kind "
                    f"FROM path_integrity_failures WHERE run_id={p}",
                    (run_id,),
                ).fetchall()
            }
            if expected is None:
                # clean_v1 — must pass (no failures).
                assert failure_kinds == set(), (
                    f"clean fixture should pass but found {failure_kinds}"
                )
            else:
                assert expected in failure_kinds, (
                    f"fixture {name!r} expected {expected!r} but "
                    f"got failures {failure_kinds!r}"
                )


def test_default_project_ids_match_advertised_catalog():
    advertised = set(path_integrity_fixtures.available_fixtures())
    defaults = set(path_integrity_fixtures._DEFAULT_PROJECT_IDS)
    assert defaults == advertised


def test_context_invariant_ignores_unrelated_sibling_contexts(fresh_db):
    path_integrity_fixtures.load_fixture(fresh_db, "clean_v1")
    root_id = fresh_db.execute(
        "SELECT t.id FROM path_targets t "
        "JOIN projects p ON p.id = t.project_id "
        "WHERE p.slug='fix_clean' AND t.path_string=''",
    ).fetchone()[0]
    p = _p(fresh_db)
    cur = fresh_db.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, "
        " parent_target_id, created_at) "
        f"VALUES ({p}, 'directory', 'sibling_a', 1, {p}, "
        f"        {p}) RETURNING id",
        (project_row_id("fix_clean"), root_id, iso8601_now()),
    )
    sibling_a = int(cur.fetchone()[0])
    cur = fresh_db.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, "
        " parent_target_id, created_at) "
        f"VALUES ({p}, 'directory', 'sibling_b', 1, {p}, "
        f"        {p}) RETURNING id",
        (project_row_id("fix_clean"), root_id, iso8601_now()),
    )
    sibling_b = int(cur.fetchone()[0])
    for event_id in ("evt-sibling-a", "evt-sibling-b"):
        fresh_db.execute(
            "INSERT INTO events ("
            " event_id, event_kind, event_type, event_name, source_type, "
            " session_id, severity, created_at, envelope) "
            f"VALUES ({p}, 'lifecycle', 'test', 'PathIntegrityTest', "
            f"        'backend', '', 'INFO', {p}, '{{}}')",
            (event_id, iso8601_now()),
        )
    for target_id, event_id, value in (
        (sibling_a, "evt-sibling-a", '{"value":"high"}'),
        (sibling_b, "evt-sibling-b", '{"value":"low"}'),
    ):
        fresh_db.execute(
            "INSERT INTO path_context_values "
            "(target_id, context_family, entry_key, value, "
            " recorded_event_id, recorded_at) "
            f"VALUES ({p}, 'posture', 'criticality', {p}, {p}, "
            f"        {p})",
            (target_id, value, event_id, iso8601_now()),
        )
    fresh_db.commit()
    run_id = path_integrity.verify_project(fresh_db, "fix_clean")
    kinds = {
        str(r[0])
        for r in fresh_db.execute(
            "SELECT invariant_kind FROM path_integrity_failures "
            f"WHERE run_id={p}",
            (run_id,),
        ).fetchall()
    }
    assert path_integrity.INVARIANT_CONTEXT_INHERITANCE not in kinds
