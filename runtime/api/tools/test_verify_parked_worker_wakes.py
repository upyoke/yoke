"""Taking over a parked QA requirement cannot restart its observation day."""

from datetime import datetime, timezone

import pytest

from runtime.api.tools.first_deployment import first_deployment_sql


@pytest.mark.parametrize("remove_predecessor_member", [False, True])
@pytest.mark.parametrize(
    "selector",
    [
        "q.plan_id=1",
        "q.method_config::jsonb->>'command' LIKE "
        "'%runtime.api.tools.verify_session_resume_origin%'",
    ],
)
def test_takeover_keeps_first_deployment_clock_and_target(
    test_db, remove_predecessor_member, selector
):
    # Replay the durable removal that real takeover writes, using native JSON operators.
    for declaration in (
        "deployment_runs(id TEXT,target_environment_id INTEGER,membership_removals TEXT)",
        "deployment_stage_receipts(run_id TEXT,status TEXT,completed_at TIMESTAMPTZ)",
        "deployment_run_items(run_id TEXT,item_id INTEGER)",
        "qa_requirements(plan_id INTEGER,deployment_run_id TEXT,deployment_member_item_id INTEGER,method_config TEXT)",
    ):
        test_db.execute(f"CREATE TEMP TABLE {declaration}")
    test_db.execute("""
        INSERT INTO deployment_runs VALUES
          ('stage',2,NULL),('first',1,NULL),('takeover',1,NULL),
          ('other-member',1,'[{"item_id":8,"transferred_to_run_id":"takeover"}]'),
          ('removed-only',1,'[{"item_id":7,"reason":"not shipped"}]')
    """)
    test_db.execute("INSERT INTO deployment_run_items VALUES('stage',7),('first',7),('takeover',7)")
    test_db.execute("""INSERT INTO qa_requirements VALUES
        (1,'takeover',7,'{"command":"yoke dev run -- python3 -m runtime.api.tools.verify_session_resume_origin"}'),
        (2,'takeover',8,'{"command":"another verifier"}')""")
    test_db.execute("""
        INSERT INTO deployment_stage_receipts VALUES
          ('stage','ready','2026-11-01T10:00:00Z'),
          ('other-member','ready','2026-11-01T10:00:00Z'),
          ('removed-only','ready','2026-11-01T10:00:00Z'),
          ('first','ready','2026-11-02T10:00:00Z'),
          ('first','ready','2026-11-02T10:10:00Z'),
          ('takeover','ready','2026-11-03T10:00:00Z');
    """)
    if remove_predecessor_member:
        test_db.execute("DELETE FROM deployment_run_items WHERE run_id='first'")
        test_db.execute("""
            UPDATE deployment_runs SET membership_removals=
              '[{"item_id":7,"transferred_to_run_id":"takeover"}]' WHERE id='first'
        """)
    query = first_deployment_sql("'takeover'", selector)
    deployed_at = test_db.execute(f"SELECT {query}").fetchone()[0]
    assert deployed_at == datetime(2026, 11, 2, 10, 10, tzinfo=timezone.utc)
