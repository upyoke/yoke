"""Seed helpers preserve native clock facts across sessions, claims and projects."""

from datetime import datetime
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import project_seed_test_helpers as projects
from yoke_core.domain.handlers import _strategy_docs_test_helpers as strategy
from runtime.api.domain import (
    coordination_claim_test_support as coordination,
    lint_session_cwd_test_helpers as lint,
    machine_qa_session_seed as machine,
    path_claim_task_test_support as paths,
    steering_claim_test_support as steering,
    strategy_execution_test_support as execution,
)
from runtime.api.fixtures.backlog_inserts import insert_epic_task

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
SEEDERS = [projects, strategy, coordination, lint, machine, paths, steering, execution]


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_seed_graph_has_native_clock_facts_and_nullable_history(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    for module in SEEDERS:
        monkeypatch.setattr(module, "utc_now", lambda: MOMENT)
    coordination.seed_project(test_db, 71, "clock-alpha")
    coordination.seed_session(test_db, "coord-clock", 71, ended=True)
    steering.seed_project(test_db, 72, "clock-beta")
    steering.seed_session(test_db, "steer-clock", 72)
    strategy.seed_session(test_db, "strategy-clock")
    strategy.seed_process_claim(test_db, "strategy-clock", released=True)
    execution.seed_blitz_item(test_db, 7, 7)
    execution.seed_session_claim(test_db, 7, "before-clock")
    execution.handoff_item_claim(test_db, 7, "before-clock", "after-clock")
    execution.seed_strategy_doc(test_db, "CLOCK-DOC", "# CLOCK-DOC\n")
    execution.link_blitz_document(test_db, 7, "CLOCK-DOC")
    coordination.seed_session(test_db, "lint-clock")
    lint.seed_item_claim(test_db, "lint-clock", 7)
    insert_epic_task(test_db, epic_id=7, task_num=1)
    lint.seed_epic_task_claim(test_db, "lint-clock", 7, 1)
    target = paths.seed_target(test_db, item_id=7, path="/tmp/clock-target")
    claim = paths.seed_item_claim(test_db, item_id=7, target_ids=(target,))
    paths.bind_claim(test_db, claim_id=claim, item_id=7, task_num=1)
    paths.seed_session(test_db, session_id="path-clock", item_id=7, task_num=1)
    machine.seed_qa_session(test_db, "machine-clock")
    monkeypatch.setattr(strategy, "SEED_SLUGS", ("CLOCK-SEED",))
    monkeypatch.setattr(strategy, "SEED_CONTENT", {"CLOCK-SEED": "# CLOCK-SEED\n"})
    strategy.seed_docs(test_db)
    rows = test_db.execute(
        "SELECT offered_at,last_heartbeat,ended_at FROM harness_sessions "
        "WHERE session_id IN ('coord-clock','steer-clock','strategy-clock','path-clock','lint-clock','before-clock','after-clock')"
    ).fetchall()
    assert len(rows) == 7
    assert all(
        isinstance(row[0], datetime) and row[0] == row[1] == MOMENT for row in rows
    )
    assert sorted(row[2] is not None for row in rows) == [False] * 6 + [True]
    claims = test_db.execute(
        "SELECT claimed_at,last_heartbeat,released_at FROM work_claims "
        "WHERE session_id IN ('strategy-clock','before-clock','after-clock','lint-clock','path-clock')"
    ).fetchall()
    assert claims and all(row[0] == row[1] == MOMENT for row in claims)
    assert all(row[2] is None or row[2] == MOMENT for row in claims)
    for sql in [
        "SELECT created_at FROM projects WHERE id IN (71,72)",
        "SELECT linked_at FROM item_strategy_docs WHERE item_id=7",
        "SELECT created_at FROM path_targets WHERE id=%s",
        "SELECT registered_at FROM path_claims WHERE id=%s",
        "SELECT declared_at FROM path_claim_targets WHERE claim_id=%s",
        "SELECT bound_at FROM path_claim_task_bindings WHERE claim_id=%s",
    ]:
        params = (
            (target,)
            if "path_targets WHERE" in sql
            else (claim,)
            if "%s" in sql
            else ()
        )
        clocks = test_db.execute(sql, params).fetchall()
        assert clocks and all(
            isinstance(row[0], datetime) and row[0] == MOMENT for row in clocks
        )
    assert test_db.execute(
        "SELECT updated_at FROM strategy_docs WHERE slug='CLOCK-SEED'"
    ).fetchone()[0] == parse_instant(strategy.SEED_UPDATED_AT)
    assert test_db.execute(
        "SELECT offered_at,last_heartbeat FROM harness_sessions WHERE session_id='machine-clock'"
    ).fetchone()[0] == parse_instant("2026-08-01T00:00:00Z")


@pytest.mark.parametrize(
    "module,seed",
    [
        (projects, lambda conn: projects.seed_project_identities(conn)),
        (strategy, lambda conn: strategy.seed_session(conn, "bad-clock")),
        (coordination, lambda conn: coordination.seed_session(conn, "bad-clock")),
        (steering, lambda conn: steering.seed_session(conn, "bad-clock", 1)),
        (execution, lambda conn: execution.seed_session(conn, "bad-clock")),
        (lint, lambda conn: lint.seed_item_claim(conn, "bad-clock", 7)),
        (
            paths,
            lambda conn: paths.seed_session(conn, session_id="bad-clock", item_id=7),
        ),
    ],
)
def test_seed_generator_refuses_naive_clock_before_insert(
    test_db, monkeypatch, module, seed
):
    monkeypatch.setattr(module, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    before = test_db.execute("SELECT count(*) FROM harness_sessions").fetchone()[0]
    with pytest.raises(InvalidInstant):
        seed(test_db)
    assert (
        test_db.execute("SELECT count(*) FROM harness_sessions").fetchone()[0] == before
    )


def test_minimal_sqlite_machine_seed_formats_native_clock_at_binding(monkeypatch):
    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, actor_id INTEGER, executor TEXT, last_heartbeat TEXT)"
        )
        monkeypatch.setattr(machine, "utc_now", lambda: MOMENT)
        machine.seed_qa_session(conn, "machine-clock")
        assert (
            conn.execute("SELECT last_heartbeat FROM harness_sessions").fetchone()[0]
            == "2026-10-09T10:26:12.345678Z"
        )
        monkeypatch.setattr(machine, "utc_now", lambda: MOMENT.replace(tzinfo=None))
        with pytest.raises(InvalidInstant):
            machine.seed_qa_session(conn, "bad-clock")
        assert conn.execute("SELECT count(*) FROM harness_sessions").fetchone()[0] == 1
