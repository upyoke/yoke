"""Composition decodes clocks only after their rows become relevant evidence."""

import importlib
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.api.fixtures.native_instant_database import blank_database
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import deployment_run_carried_work_sources as sources
from yoke_core.domain import deployment_runs_crud_query as runs
from yoke_core.domain.deployment_flow_succession import succession_chains
from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

STAMP = parse_instant("2026-10-10T23:30:00.123456Z")
DRIVER_STAMP = parse_instant("2026-10-10T23:07:54.695930Z")
history = importlib.import_module(
    "yoke_core.domain.migrations.0070_native_domain_instants"
)


@pytest.fixture
def clocks():
    with blank_database() as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("SET LOCAL DateStyle = 'ISO, MDY'")
        conn.execute("CREATE TABLE projects (id integer PRIMARY KEY, slug text)")
        conn.execute("INSERT INTO projects VALUES (1,'project')")
        conn.execute(
            "CREATE TABLE items (id integer PRIMARY KEY, project_id integer, "
            "merged_at text, merge_queue_landed_at text, resolution_ref text)"
        )
        conn.execute(
            "CREATE TABLE item_worktrees (item_id integer, branch text, commit_sha text)"
        )
        conn.execute(
            "CREATE TABLE deployment_flows (id text PRIMARY KEY, project_id integer, "
            "status text, supersedes_flow_id text, created_at text, "
            "target_environment_id integer, target_tier text)"
        )
        conn.execute(
            "CREATE TABLE deployment_runs (id text PRIMARY KEY, project_id integer, "
            "flow text, release_lineage text, status text, created_at text)"
        )
        for item_id, stamp in (
            (1, format_instant(STAMP)),
            (2, "2026-03-09 02:32:26"),
            (3, "2026-07-30 15:00:27.569899+00"),
        ):
            conn.execute(
                "INSERT INTO items VALUES (%s,1,%s,NULL,NULL)", (item_id, stamp)
            )
        for flow_id, status, predecessor, stamp in (
            ("root", "disabled", None, "2026-03-08 22:42:21"),
            ("successor", "active", "root", format_instant(STAMP)),
            ("unrelated", "active", None, "2026-03-08 22:42:21"),
            ("unrelated-offset", "active", None, "2026-07-30 15:00:27.569899+00"),
        ):
            conn.execute(
                "INSERT INTO deployment_flows VALUES (%s,1,%s,%s,%s,1,'production')",
                (flow_id, status, predecessor, stamp),
            )
        # Aware datetime parameters reproduce the candidate driver's write
        # into an old TEXT column, including PostgreSQL's short +00 offset.
        conn.execute(
            "INSERT INTO deployment_runs VALUES ('run-clock-filter',1,'successor',%s,"
            "'created',%s)",
            ("a" * 40, DRIVER_STAMP),
        )
        yield conn


def _resolve(conn, times=None):
    times = {"a" * 40: STAMP} if times is None else times
    resolved, warnings = {}, []
    sources._resolve_item_metadata(
        conn,
        project_id=1,
        source=SimpleNamespace(
            commit_time=lambda commit: times[commit],
            resolve_commit=lambda _: "",
        ),
        base="b" * 40,
        head="a" * 40,
        commits=list(times),
        known_items={item_id: f"ITEM-{item_id}" for item_id in (1, 2, 3)},
        resolved=resolved,
        warnings=warnings,
    )
    assert warnings == []
    return resolved


@pytest.mark.parametrize("native", [False, True])
def test_composition_ignores_unrelated_historical_clocks(clocks, monkeypatch, native):
    if native:
        history.apply(clocks)
        history.invariants(clocks)
    decoded = []

    def decode(value):
        decoded.append(value)
        return parse_instant(value)

    monkeypatch.setattr(sources, "parse_instant", decode)
    assert succession_chains(clocks, ["root", "unrelated"]) == {
        "root": ("root", "successor"),
        "unrelated": ("unrelated",),
    }
    assert _resolve(clocks) == {"a" * 40: {1}}
    assert decoded == [STAMP if native else format_instant(STAMP)]


@pytest.mark.parametrize("field", ["merged_at", "merge_queue_landed_at"])
def test_relevant_landing_clock_still_requires_strict_decoding(clocks, field):
    clocks.execute(
        f"UPDATE items SET {field}=%s WHERE id=1", ("2026-10-10 23:30:00.123456+00",)
    )
    with pytest.raises(InvalidInstant):
        _resolve(clocks)


def test_relevant_successor_clock_still_requires_strict_decoding(clocks):
    clocks.execute(
        "UPDATE deployment_flows SET created_at=%s WHERE id='successor'",
        ("2026-10-10 23:30:00.123456+00",),
    )
    with pytest.raises(InvalidInstant):
        succession_chains(clocks, ["root"])


@pytest.mark.parametrize("offset", [-600000001, -600000000, 600000000, 600000001])
def test_sql_window_preserves_inclusive_microsecond_cutoff(clocks, offset):
    clocks.execute(
        "UPDATE items SET merged_at=%s WHERE id=1",
        (format_instant(STAMP + timedelta(microseconds=offset)),),
    )
    expected = {"a" * 40: {1}} if abs(offset) <= 600000000 else {}
    assert _resolve(clocks) == expected


def test_unqualified_commit_clocks_do_not_decode_landing_candidates(clocks):
    assert _resolve(clocks, {"a" * 40: None}) == {}


def test_recorded_commit_evidence_survives_outside_landing_window(clocks):
    clocks.execute("UPDATE items SET resolution_ref=%s WHERE id=2", ("a" * 40,))
    assert _resolve(clocks) == {"a" * 40: {1, 2}}


def test_driver_text_clock_converts_at_boot_and_retry_reads_do_not_decode_it(
    clocks, monkeypatch
):
    raw = clocks.execute("SELECT created_at FROM deployment_runs").fetchone()[0]
    assert raw == "2026-10-10 23:07:54.69593+00"
    monkeypatch.setattr(
        runs,
        "connect",
        lambda *_: SimpleNamespace(execute=clocks.execute, close=lambda: None),
    )
    assert runs.cmd_get("run-clock-filter", field="status") == "created"
    assert runs.cmd_get("run-clock-filter", field="release_lineage") == "a" * 40
    row = runs.cmd_get("run-clock-filter").split("|")
    assert row[RUN_FIELDS.index("created_at")] == raw
    with pytest.raises(InvalidInstant):
        runs.cmd_get("run-clock-filter", field="created_at")
    history.apply(clocks)
    history.invariants(clocks)
    assert (
        clocks.execute("SELECT created_at FROM deployment_runs").fetchone()[0]
        == DRIVER_STAMP
    )
    assert runs.cmd_get("run-clock-filter", field="created_at") == format_instant(
        DRIVER_STAMP
    )
