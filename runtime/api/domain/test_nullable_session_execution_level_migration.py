"""The migration clears only the retired session-level placeholder."""

from pathlib import Path

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module


def test_migration_clears_unresolved_levels_and_replays(test_db):
    path = (
        Path(migrations.__file__).parent
        / "0124_nullable_session_execution_level.py"
    )
    module = load_migration_module(path, path.stem)
    assert module.MINIMUM_SERVING_VERSION == "next-release"

    test_db.execute(
        "ALTER TABLE harness_sessions "
        "ALTER COLUMN execution_level SET NOT NULL, "
        "ALTER COLUMN execution_level SET DEFAULT 'primary'"
    )
    test_db.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, workspace, project_id, offered_at, last_heartbeat) "
        "VALUES ('unresolved', 'codex', 'openai', '/tmp', 1, now(), now()), "
        "('resolved', 'codex', 'openai', '/tmp', 1, now(), now())"
    )
    test_db.execute(
        "UPDATE harness_sessions SET execution_level = 'SENIOR' WHERE session_id = 'resolved'"
    )
    for _ in range(2):
        module.apply(test_db)
        module.invariants(test_db)
        rows = test_db.execute(
            "SELECT session_id, execution_level FROM harness_sessions "
            "WHERE session_id IN ('resolved', 'unresolved') ORDER BY session_id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [("resolved", "SENIOR"), ("unresolved", None)]

    test_db.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, workspace, project_id, offered_at, last_heartbeat) "
        "VALUES ('new', 'codex', 'openai', '/tmp', 1, now(), now())"
    )
    assert test_db.execute(
        "SELECT execution_level FROM harness_sessions WHERE session_id = 'new'"
    ).fetchone()[0] is None
