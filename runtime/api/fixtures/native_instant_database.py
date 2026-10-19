"""Isolated blank PostgreSQL databases for native instant conversion checks."""

from contextlib import contextmanager


#: Instant columns born native TIMESTAMPTZ after the cutover; the frozen
#: history never converts them, but the live roster still declares them.
BORN_NATIVE_AFTER_HISTORY = frozenset(
    {("qa_host_waits", "queued_at"), ("qa_host_waits", "settled_at")}
    | {("merge_queue_landing_attempts", c) for c in ("enqueued_at", "opened_at")}
    | {("merge_queue_landing_attempts", "closed_at")}
    | {("deployment_run_timings", "recorded_at")}
    | {("qa_plan_execution_adoptions", "adopted_at")}
    | {
        ("teammate_invite_codes", column)
        for column in (
            "created_at",
            "expires_at",
            "consumed_at",
            "revoked_at",
            "replaced_at",
        )
    }
)


@contextmanager
def blank_database():
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_test_database,
    )

    name = create_test_database()
    conn = connect_test_database(name)
    try:
        yield conn
    finally:
        conn.close()
        drop_test_database(name)
