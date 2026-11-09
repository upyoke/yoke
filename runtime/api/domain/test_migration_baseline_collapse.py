"""The baseline transition is exact, atomic, idempotent and guard preserving."""

import json
import sqlite3

import pytest

from yoke_core.domain import migrations
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.migration_baseline import declared_baseline
from yoke_core.domain import migration_baseline_collapse as collapse
from yoke_core.domain.migration_content_transition_guard import (
    adoption_transition_guard_is_enforced,
)
from yoke_core.domain.migration_history import HistoryError, history_dir
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_ADOPTION_EVIDENCE_CONTRACT as EVIDENCE,
    YOKE_LEDGER_CONTRACT as LEDGER,
    ensure_yoke_migration_ledger,
)


BASELINE = declared_baseline(history_dir(migrations))
PREDECESSORS = json.loads(BASELINE.baseline_predecessors.read_text())


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, test_db):
    if request.param == "postgres":
        conn = test_db
        conn.execute("ALTER TABLE applied_migrations DISABLE TRIGGER USER")
        conn.execute("DELETE FROM applied_migrations")
        conn.execute("ALTER TABLE applied_migrations ENABLE TRIGGER USER")
    else:
        conn = sqlite3.connect(":memory:")
        ensure_yoke_migration_ledger(conn)
    marker = "%s" if request.param == "postgres" else "?"
    for name, digest in PREDECESSORS.items():
        conn.execute(
            "INSERT INTO applied_migrations (migration_name,applied_at,applied_by,content_sha256) "
            f"VALUES ({marker},{marker},{marker},{marker})",
            (name, "2026-11-01T00:00:00Z", "birth", digest),
        )
    conn.commit()
    yield conn
    if request.param == "sqlite":
        conn.close()


def _rows(conn):
    return tuple(
        tuple(row[i] for i in range(3))
        for row in conn.execute(
            "SELECT migration_name,content_sha256,minimum_serving_version FROM applied_migrations ORDER BY migration_name"
        ).fetchall()
    )


def _guarded(conn):
    assert adoption_transition_guard_is_enforced(conn, LEDGER, EVIDENCE)


def test_exact_predecessor_set_collapses_once_and_keeps_delete_guard(database):
    _guarded(database)
    assert len(_rows(database)) == len(PREDECESSORS) == 102
    assert collapse.collapse_baseline(
        database, BASELINE, LEDGER, running_version="9.0.0", applied_by="boot-converge"
    )
    database.commit()
    assert _rows(database) == ((BASELINE.name, BASELINE.content_sha256, "9.0.0"),)
    assert not collapse.collapse_baseline(
        database, BASELINE, LEDGER, running_version="10.0.0", applied_by="boot-converge"
    )
    assert _rows(database)[0][2] == "9.0.0"
    _guarded(database)
    with pytest.raises(Exception, match="membership is immutable"):
        with savepoint(database, "prove_delete_guard", owns=False):
            database.execute("DELETE FROM applied_migrations")
    assert _rows(database) == ((BASELINE.name, BASELINE.content_sha256, "9.0.0"),)


@pytest.mark.parametrize("kind", ["missing", "unexpected", "changed", "null"])
def test_inexact_identity_set_refuses_without_mutation(database, monkeypatch, kind):
    # Substitute the read-only manifest input, not protected live evidence.
    before = _rows(database)
    expected = dict(PREDECESSORS)
    first = next(iter(expected))
    if kind == "missing":
        expected["0000_missing"] = "a" * 64
    elif kind == "unexpected":
        del expected[first]
    elif kind == "changed":
        expected[first] = "a" * 64
    else:
        expected[first] = None
    monkeypatch.setattr(collapse.json, "loads", lambda _raw: expected)
    with pytest.raises(
        HistoryError,
        match="migration_baseline_(ledger_mismatch|transition_unavailable)",
    ):
        collapse.collapse_baseline(
            database,
            BASELINE,
            LEDGER,
            running_version="9.0.0",
            applied_by="boot-converge",
        )
    assert _rows(database) == before
    _guarded(database)


def test_failure_after_delete_restores_evidence_and_caller_work(database, monkeypatch):
    before = _rows(database)
    database.execute("CREATE TEMP TABLE caller_work (value INTEGER)")
    database.execute("INSERT INTO caller_work VALUES (1)")

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected baseline insert failure")

    monkeypatch.setattr(collapse, "record_applied", fail)
    with pytest.raises(RuntimeError, match="injected baseline insert failure"):
        collapse.collapse_baseline(
            database,
            BASELINE,
            LEDGER,
            running_version="9.0.0",
            applied_by="boot-converge",
        )
    assert _rows(database) == before
    assert database.execute("SELECT value FROM caller_work").fetchone()[0] == 1
    _guarded(database)


def test_baseline_coexisting_with_predecessors_is_not_a_completed_transition(database):
    from yoke_core.domain.migration_boot_ledger import record_applied

    record_applied(database, BASELINE, ledger=LEDGER, applied_by="partial", content_sha256=BASELINE.content_sha256)
    before = _rows(database)
    with pytest.raises(HistoryError, match="coexists with predecessor membership"):
        collapse.collapse_baseline(database, BASELINE, LEDGER, running_version="9.0.0", applied_by="boot")
    assert _rows(database) == before
    _guarded(database)


def test_real_boot_collapses_predecessors_and_second_boot_is_current(
    database, monkeypatch
):
    from yoke_core.domain.migration_boot_apply import apply_pending
    from yoke_core.domain.migration_history import ordered_entries

    result = apply_pending(
        database,
        history=ordered_entries(history_dir(migrations)),
        ledger=LEDGER,
        applied_by="boot-converge",
        administering_env="",
        running_version="9.0.0",
        attribution={
            "session_id": "boot",
            "actor_id": "boot",
            "source_branch": "main",
            "source_commit": "c" * 40,
        },
        model_name="primary",
        dump_backup=lambda *_: pytest.fail("named restore point already supplied"),
        external_restore_point="snapshot:before-baseline",
    )
    assert result.applied == (BASELINE.name,)
    assert _rows(database) == ((BASELINE.name, BASELINE.content_sha256, "9.0.0"),)
    second = apply_pending(
        database,
        history=ordered_entries(history_dir(migrations)),
        ledger=LEDGER,
        applied_by="boot-converge",
        administering_env="",
        running_version="9.0.0",
        attribution={},
        model_name="",
        dump_backup=lambda *_: pytest.fail("current boot needs no backup"),
    )
    assert not second.changed


def test_newborn_universe_records_only_baseline(test_db):
    assert [
        row[0]
        for row in test_db.execute("SELECT migration_name FROM applied_migrations")
    ] == [BASELINE.name]
