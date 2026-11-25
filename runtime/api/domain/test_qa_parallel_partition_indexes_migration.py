"""Boot indexes support per-session custody and migration retires old keys."""

from pathlib import Path

import pytest

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module


@pytest.mark.parametrize(
    ("old_suffix", "new_suffix", "subject", "predicate"),
    [
        ("active", "item_session_active", "item_id, transition_id", "item_id IS NOT NULL"),
        (
            "standalone_active", "standalone_session_active", "standalone_plan_id",
            "standalone_plan_id IS NOT NULL",
        ),
        (
            "deployment_member_stage_active", "deployment_member_session_active",
            "deployment_run_id, deployment_stage, deployment_member_item_id",
            "deployment_member_item_id IS NOT NULL",
        ),
    ],
)
def test_boot_uses_session_keys_and_migration_replays(
    test_db, old_suffix, new_suffix, subject, predicate
):
    path = Path(migrations.__file__).parent / "0125_qa_parallel_partition_indexes.py"
    module = load_migration_module(path, path.stem)
    assert module.MINIMUM_SERVING_VERSION == "next-release"
    old = f"idx_qa_plan_executions_{old_suffix}"
    new = f"idx_qa_plan_executions_{new_suffix}"
    test_db.execute(
        f"CREATE UNIQUE INDEX {old} ON qa_plan_executions ({subject}) "
        f"WHERE {predicate} AND state IN ('active','waiting','walking','awaiting_walk_review')"
    )

    for _ in range(2):
        module.apply(test_db)
        assert test_db.execute("SELECT to_regclass(%s)", (old,)).fetchone()[0] is None
        index = test_db.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() "
            "AND tablename = 'qa_plan_executions' AND indexname = %s",
            (new,),
        ).fetchone()
        assert f"UNIQUE INDEX {new}" in index[0]
        assert f"({subject}, session_id)" in index[0]
