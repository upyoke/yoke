"""Path and deployment fixture clocks remain native through their SQL owners."""

from datetime import datetime
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import path_integrity_fixtures as catalog
from yoke_core.domain import path_integrity_fixtures_helpers as paths
from runtime.api import path_context_test_helpers as context
from runtime.api.domain._path_integrity_test_helpers import path_integrity_db
from runtime.api.fixtures import deployment_scoped_qa_run_fixture as deployment

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
OPAQUE = "captured 2026-10-09 10:26:12+00:00"


@pytest.mark.parametrize("zone", ZONES)
def test_continuity_fixture_graph_keeps_native_clocks_and_context_values(
    tmp_path, monkeypatch, zone
):
    monkeypatch.setattr(paths, "utc_now", lambda: MOMENT)
    with path_integrity_db(tmp_path) as conn:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        assert isinstance(paths._now_parameter(conn), datetime)
        for name in ("ambiguous_continuity_v1", "conflicting_context_inheritance_v1"):
            catalog.load_fixture(conn, name)
        for table, column, condition in (
            ("projects", "created_at", "id=ANY(%s)"),
            ("path_targets", "created_at", "TRUE"),
            ("path_snapshots", "built_at", "TRUE"),
            ("path_integrity_fixtures", "seeded_at", "TRUE"),
            ("path_moves", "recorded_at", "TRUE"),
            ("path_context_values", "recorded_at", "TRUE"),
        ):
            parameters = (
                ([paths.project_row_id("fix_cont"), paths.project_row_id("fix_ctx")],)
                if table == "projects"
                else ()
            )
            rows = conn.execute(
                f"SELECT {column} FROM {table} WHERE {condition}", parameters
            ).fetchall()
            assert rows and all(
                isinstance(row[0], datetime) and row[0] == MOMENT for row in rows
            )
        assert {
            row[0]
            for row in conn.execute("SELECT value FROM path_context_values").fetchall()
        } == {'{"value":"high"}', '{"value":"low"}'}


@pytest.mark.parametrize("zone", ZONES)
def test_context_fixture_event_and_target_keep_native_clock_and_opaque_text(
    tmp_path, monkeypatch, zone
):
    monkeypatch.setattr(context, "utc_now", lambda: MOMENT)
    conn = context.init_minimal_schema(str(tmp_path / "clock-context"))
    try:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        event = context.emit_event(conn, name=OPAQUE)
        target = context.mint_target(conn, "yoke", OPAQUE)
        row = conn.execute(
            "SELECT created_at,event_name,envelope FROM events WHERE event_id=%s",
            (event,),
        ).fetchone()
        assert tuple(row) == (MOMENT, OPAQUE, "{}") and isinstance(row[0], datetime)
        row = conn.execute(
            "SELECT created_at,path_string FROM path_targets WHERE id=%s", (target,)
        ).fetchone()
        assert tuple(row) == (MOMENT, OPAQUE) and isinstance(row[0], datetime)
        assert isinstance(
            conn.execute("SELECT created_at FROM projects WHERE id=1").fetchone()[0],
            datetime,
        )
        assert isinstance(context.NOW, datetime)
    finally:
        conn.close()


@pytest.mark.parametrize("zone", ZONES)
def test_frozen_deployment_and_verdict_fixture_bind_native_clocks(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(deployment, "utc_now", lambda: MOMENT)
    requirement = deployment.seed_member_qa_case(
        test_db, run_id="clock-deployment", member_item_id=7
    )
    before = test_db.execute(
        "SELECT created_at,composition_frozen_at,requirement_snapshot FROM deployment_runs WHERE id='clock-deployment'"
    ).fetchone()
    assert tuple(before[:2]) == (MOMENT, MOMENT) and isinstance(before[0], datetime)
    member = test_db.execute(
        "SELECT added_at,requirement_snapshot FROM deployment_run_items WHERE run_id='clock-deployment' AND item_id=7"
    ).fetchone()
    assert member[0] == MOMENT and isinstance(member[0], datetime)
    execution = deployment.record_case_verdict(
        test_db, requirement, "pass", evidence=True
    )
    verdict_clock = parse_instant("2026-09-18T00:02:00Z")
    row = test_db.execute(
        "SELECT created_at,started_at,completed_at FROM qa_runs WHERE id=%s",
        (execution,),
    ).fetchone()
    assert tuple(row) == (verdict_clock,) * 3 and isinstance(row[0], datetime)
    artifact = test_db.execute(
        "SELECT created_at,artifact_handle FROM qa_artifacts WHERE qa_run_id=%s",
        (execution,),
    ).fetchone()
    assert artifact[0] == verdict_clock and isinstance(artifact[0], datetime)
    assert artifact[1] == f"evidence://requirement-{requirement}"
    assert (
        test_db.execute(
            "SELECT requirement_snapshot FROM deployment_runs WHERE id='clock-deployment'"
        ).fetchone()[0]
        == before[2]
    )
    assert (
        test_db.execute(
            "SELECT requirement_snapshot FROM deployment_run_items WHERE run_id='clock-deployment' AND item_id=7"
        ).fetchone()[0]
        == member[1]
    )


@pytest.mark.parametrize(
    "owner,invoke",
    [
        (paths, lambda conn: paths.ensure_project_row(conn, "fix_cont")),
        (
            paths,
            lambda conn: paths.record_fixture_row(
                conn,
                name="clock",
                description=OPAQUE,
                project_id="fix_cont",
                expected_invariant_kind=None,
            ),
        ),
        (
            paths,
            lambda conn: paths.mint_target(
                conn,
                project_id="fix_cont",
                path_string=OPAQUE,
                kind="file",
                parent_target_id=None,
            ),
        ),
        (
            paths,
            lambda conn: paths.mint_snapshot(
                conn, project_id="fix_cont", commit_sha=OPAQUE, target_ids=[]
            ),
        ),
        (paths, lambda conn: catalog.load_fixture(conn, "ambiguous_continuity_v1")),
        (
            paths,
            lambda conn: catalog.load_fixture(
                conn, "conflicting_context_inheritance_v1"
            ),
        ),
        (context, lambda conn: context.emit_event(conn)),
        (context, lambda conn: context.mint_target(conn, "yoke", OPAQUE)),
        (
            deployment,
            lambda conn: deployment.seed_frozen_scoped_qa_run(
                conn,
                run_id="clock",
                project="yoke",
                flow="clock",
                stages=[],
                item_id=7,
                lineage="a" * 40,
            ),
        ),
        (
            deployment,
            lambda conn: deployment.seed_run_standing_on_qa_stage(
                conn,
                run_id="clock",
                project="yoke",
                stages=[],
                members=(7,),
                lineage="a" * 40,
            ),
        ),
    ],
)
def test_naive_generated_fixture_clock_refuses_before_sql(monkeypatch, owner, invoke):
    monkeypatch.setattr(owner, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    with pytest.raises(InvalidInstant):
        invoke(object())


def test_explicit_sqlite_path_fixture_clock_is_canonical(monkeypatch):
    monkeypatch.setattr(paths, "utc_now", lambda: MOMENT)
    with sqlite3.connect(":memory:") as conn:
        assert paths._now_parameter(conn) == "2026-10-09T10:26:12.345678Z"
