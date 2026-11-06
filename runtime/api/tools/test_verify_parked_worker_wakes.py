"""Taking over a parked QA requirement cannot restart its observation day."""

import sqlite3

from runtime.api.tools.verify_parked_worker_wakes import first_deployment_sql


def test_takeover_keeps_first_deployment_clock_and_target():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE deployment_runs(id TEXT,target_environment_id INTEGER);
        CREATE TABLE deployment_stage_receipts(run_id TEXT,status TEXT,completed_at TEXT);
        CREATE TABLE deployment_run_items(run_id TEXT,item_id INTEGER);
        CREATE TABLE qa_requirements(plan_id INTEGER,deployment_run_id TEXT,deployment_member_item_id INTEGER);
        INSERT INTO deployment_runs VALUES('stage',2),('first',1),('takeover',1);
        INSERT INTO deployment_run_items VALUES('stage',7),('first',7),('takeover',7);
        INSERT INTO qa_requirements VALUES(1,'takeover',7);
        INSERT INTO deployment_stage_receipts VALUES
          ('stage','ready','2026-11-01T10:00:00Z'),
          ('first','ready','2026-11-02T10:00:00Z'),
          ('first','ready','2026-11-02T10:10:00Z'),
          ('takeover','ready','2026-11-03T10:00:00Z');
    """)
    query = first_deployment_sql("'takeover'", 1)
    assert conn.execute(f"SELECT {query}").fetchone()[0] == "2026-11-02T10:10:00Z"
