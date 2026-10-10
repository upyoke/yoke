"""Native supporting clocks for reclaim, carry and disposable review fixtures."""

from datetime import datetime, timedelta
import importlib

import pytest

from yoke_contracts.timestamps import parse_instant

NOW = parse_instant("2060-10-08T00:00:00.123456Z")
OPAQUE = "2060-10-08T00:00:00+09:00 unchanged"


@pytest.mark.parametrize(
    "module",
    ["runtime.api.test_sessions", "runtime.api.sessions_api_stale_test_helpers"],
)
@pytest.mark.parametrize("fixture_name", ["conn", "ownership_conn"])
def test_actual_reclaim_fixtures_declare_native_clocks_and_seed_items(
    tmp_path, module, fixture_name
):
    from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

    owner = importlib.import_module(module)
    generator = getattr(owner, fixture_name).__wrapped__(tmp_path)
    value = next(generator)
    conn = value[0] if fixture_name == "ownership_conn" else value
    try:
        catalog = {
            (row[0], row[1]): row[2]
            for row in conn.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public'"
            ).fetchall()
        }
        declared = set(STORED_INSTANT_COLUMNS) & set(catalog)
        assert declared
        assert all(catalog[key] == "timestamp with time zone" for key in declared)
        assert catalog["actors", "created_at"] == "timestamp with time zone"
        if fixture_name == "ownership_conn":
            row = conn.execute(
                "SELECT created_at, updated_at, project_sequence FROM items WHERE id=100"
            ).fetchone()
            expected = parse_instant("2026-03-01T00:00:00Z")
            assert all(isinstance(v, datetime) and v == expected for v in row[:2])
            assert row[2] == (100 if module == "runtime.api.test_sessions" else None)
    finally:
        generator.close()


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kathmandu"])
def test_stale_event_schema_binds_native_microseconds(test_db, zone):
    from runtime.api import sessions_api_stale_test_helpers as fixtures
    from runtime.api.test_sessions_api_stale_reclaim_misc import (
        TestStaleSessionSweepEvent,
    )

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    # Verify the actual three event DDL owners on separate empty tables,
    # preventing the canonical test schema from masking their declarations.
    test_db.execute("ALTER TABLE events RENAME TO retained_fixture_events")
    try:
        for ddl in [
            fixtures.EVENTS_TABLE_FOR_STALE_DETECTION,
            fixtures._OWNERSHIP_EXTRA_TABLES,
            TestStaleSessionSweepEvent._SWEEP_EVENT_TABLES,
        ]:
            fixtures.apply_ddl_statements(test_db, ddl)
            assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
            kind = test_db.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='events' AND column_name='created_at'"
            ).fetchone()[0]
            assert kind == "timestamp with time zone"
            test_db.execute(
                "INSERT INTO events (id, event_name, created_at, envelope) VALUES (1, 'clock', %s, %s)",
                (NOW, OPAQUE),
            )
            row = test_db.execute(
                "SELECT created_at, envelope FROM events WHERE id=1"
            ).fetchone()
            assert (
                isinstance(row[0], datetime)
                and row[0] == NOW
                and row[0].microsecond == 123456
            )
            assert row[1] == OPAQUE
            test_db.execute("DROP TABLE events")
    finally:
        test_db.execute("ALTER TABLE retained_fixture_events RENAME TO events")


def test_stale_and_review_generators_are_strict_native_clocks(monkeypatch):
    from runtime.api import sessions_api_stale_test_helpers as stale
    from runtime.api.tools import frontier_graph_review as review

    for owner in [stale, review]:
        monkeypatch.setattr(owner, "utc_now", lambda: NOW)
    assert stale._ago_minutes(3) == NOW - timedelta(minutes=3)
    assert stale._now_instant() == NOW
    assert review._stamp(hours=2) == NOW - timedelta(hours=2)
    for owner in [stale, review]:
        monkeypatch.setattr(owner, "utc_now", lambda: datetime(2060, 10, 8))
    for generate in [stale._now_instant, lambda: stale._ago_minutes(1), review._stamp]:
        with pytest.raises(ValueError):
            generate()


def test_carry_fixture_retains_native_merged_microseconds(monkeypatch):
    from runtime.api import test_strategize_carry_test_helpers as fixtures

    monkeypatch.setattr(fixtures, "utc_now", lambda: NOW)
    conn = fixtures._make_db()
    try:
        ids = fixtures._seed_landed_items(conn, count=1, title_prefix=OPAQUE)
        row = conn.execute(
            "SELECT merged_at, title FROM items WHERE id=%s", (ids[0],)
        ).fetchone()
        assert isinstance(row[0], datetime) and row[0] == NOW - timedelta(days=5)
        assert row[0].microsecond == 123456 and row[1] == f"{OPAQUE} {ids[0]}"
    finally:
        conn.close()
    monkeypatch.setattr(fixtures, "utc_now", lambda: datetime(2060, 10, 8))
    with pytest.raises(ValueError):
        fixtures._seed_landed_items(object(), count=1)


def test_actual_frontier_review_sql_owners_keep_native_instants(test_db, monkeypatch):
    from runtime.api.tools import frontier_graph_review as fixtures
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    monkeypatch.setattr(fixtures, "utc_now", lambda: NOW)
    monkeypatch.setattr(fixtures, "PROJECTS", {"YOK": (1, "yoke", "Yoke", 0)})
    fixtures._seed_projects(test_db, "today")
    sequence = 17
    ref = f"YOK-{sequence}"
    session_id = f"fgr-{ref}"
    run_id = f"fgr-run-{ref}-prod"
    node = {
        "ref": ref,
        "band": "done",
        "stage": "done",
        "title": OPAQUE,
        "claim": "codex-cli · active",
        "deploy": "prod ✓",
        "envs": ["prod"],
    }
    fixtures._seed_item(test_db, node, resolve_current_workflow_pin(test_db, "dash"))
    session = test_db.execute(
        "SELECT offered_at, last_heartbeat FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    claim = test_db.execute(
        "SELECT claimed_at, last_heartbeat FROM work_claims WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    run = test_db.execute(
        "SELECT created_at, started_at, completed_at FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert all(
        isinstance(v, datetime) and v.microsecond == 123456
        for v in [*session, *claim, *run]
    )
    fixtures._retire_fixtures(test_db)
    released = test_db.execute(
        "SELECT released_at FROM work_claims WHERE session_id=%s", (session_id,)
    ).fetchone()[0]
    ended = test_db.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (session_id,)
    ).fetchone()[0]
    assert released == ended == NOW
