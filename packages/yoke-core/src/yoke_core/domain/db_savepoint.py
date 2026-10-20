"""Error isolation for writes that may run inside a caller's transaction.

A function that owns its connection's transaction may roll the whole
transaction back on error. A function running on a caller's open
transaction must not: a full rollback would discard every write the caller
made before the call while the caller goes on to report success. Such a
function wraps its own writes in :func:`savepoint`, which undoes only them.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


class SavepointLostError(RuntimeError):
    """The caller's transaction ended inside a savepoint it had opened."""


@contextmanager
def savepoint(conn: Any, name: str, *, owns: bool) -> Iterator[None]:
    """Run the block so an error undoes only the block's own writes.

    ``owns=True`` means the block owns the transaction (it may commit inside
    the block): an error rolls the whole transaction back. Otherwise the
    block runs inside ``SAVEPOINT name``; an error rolls back to it and
    re-raises, leaving the caller's earlier writes in place. When the
    savepoint can no longer be released or rolled back to, something inside
    the block ended the caller's transaction and its earlier writes are
    gone, so :class:`SavepointLostError` is raised instead of the caller
    continuing as though they persisted.
    """
    if owns:
        try:
            yield
        except BaseException:
            conn.rollback()
            raise
        return
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException as exc:
        _end(conn, name, rollback=True, cause=exc)
        raise
    _end(conn, name, rollback=False, cause=None)


def _end(conn: Any, name: str, *, rollback: bool, cause: BaseException | None) -> None:
    try:
        if rollback:
            conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except Exception as exc:
        inner = f"; inner error: {cause}" if cause is not None else ""
        raise SavepointLostError(
            f"savepoint_lost: savepoint {name} no longer exists ({exc}{inner}). "
            "A write inside it committed or rolled back the caller's "
            "transaction, so the caller's earlier writes were not kept and "
            "the operation must not report success. Fix the inner write that "
            "ended the borrowed transaction, then rerun the operation"
        ) from exc


__all__ = ["SavepointLostError", "savepoint"]
