"""Resolve immutable release inputs once, with no transaction open during I/O."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_SOURCE_CONNECTION = ContextVar("deployment_qa_source_connection", default=None)


def dispatch_input_operation(function):
    @wraps(function)
    def run(conn, *args, **kwargs):
        token = _SOURCE_CONNECTION.set(conn)
        try:
            return function(conn, *args, **kwargs)
        finally:
            _SOURCE_CONNECTION.reset(token)

    return run


def require_transaction_free_source_read():
    conn = _SOURCE_CONNECTION.get()
    if conn is None:
        return
    from psycopg.pq import TransactionStatus

    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError(
            "deployment_qa_source_inputs_changed: a source input was not prepared "
            "before the dispatch transaction; re-drive this QA stage to refresh "
            "its immutable source inputs before retrying the write"
        )


@contextmanager
def transaction_free_reads(conn):
    """The dispatch owns its connection and commits before external reads."""
    conn.commit()
    previous = conn.autocommit
    conn.autocommit = True
    try:
        yield
    finally:
        if not conn.closed:
            conn.autocommit = previous


def prepare_release_inputs(conn, stage, *, run_id):
    target = stage.get("target") or {}
    if target.get("kind") != "persistent_environment":
        return
    if stage.get("scope") == "item":
        projects = (
            "SELECT i.project_id FROM items i JOIN deployment_run_items m "
            "ON m.item_id=i.id WHERE m.run_id=%s"
        )
    else:
        projects = "SELECT project_id FROM deployment_runs WHERE id=%s"
    rows = conn.execute(
        "SELECT c.project_id FROM project_capabilities c WHERE c.type=%s "
        f"AND c.project_id IN ({projects}) ORDER BY c.project_id",
        ("release_pin", run_id),
    ).fetchall()
    if not rows:
        return
    from yoke_core.domain.deployment_qa_execution_target import _persistent_target

    with transaction_free_reads(conn):
        for row in rows:
            project_id = int(row["project_id"] if hasattr(row, "keys") else row[0])
            _persistent_target(
                conn, project_id, str(target.get("environment") or ""), run_id
            )
