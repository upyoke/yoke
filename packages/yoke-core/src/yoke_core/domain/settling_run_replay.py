"""Replay a settling run's settlement when the record blocking it clears.

A run that reached its shared gates and could not close its members stays
``executing`` and settling, naming what blocked it. The blocker is usually a
QA record only its own holder can terminalize, so clearing it happens in a
different call than the settlement that refused — and nothing used to connect
the two. The run then sat green-but-executing until somebody re-drove
``deployment-runs update status succeeded`` by hand, which is exactly the
manual step a settled shared gate is supposed to make unnecessary.

Terminalizing such a record calls :func:`replay_settling_runs_for_item`, so
the run finishes on the same event that unblocked it.

Settlement itself terminalizes records — it supersedes residue that recorded
no result — so this has to stay out of its way. :func:`settlement_in_progress`
marks that window, and a replay requested inside it is dropped: the
settlement already running is about to evaluate the very member that just
became closeable.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

from yoke_core.domain.schema_common import _table_exists

_settling: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "settlement_in_progress", default=False
)


@contextmanager
def settlement_in_progress() -> Iterator[None]:
    """Mark the window in which settlement owns the run's completion."""
    token = _settling.set(True)
    try:
        yield
    finally:
        _settling.reset(token)


def settling_runs_for_item(conn: Any, *, item_id: int) -> list[str]:
    """Runs that are settling and carry this item as a final member."""
    if not all(
        _table_exists(conn, name) for name in ("deployment_runs", "deployment_run_items")
    ):
        return []
    rows = conn.execute(
        "SELECT dr.id FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id=dr.id "
        "WHERE dri.item_id=%s AND dr.status='executing' "
        "AND dr.settling_at IS NOT NULL ORDER BY dr.id",
        (int(item_id),),
    ).fetchall()
    return [str(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


def replay_settling_runs_for_item(conn: Any, *, item_id: int) -> None:
    """Continue every settling run this item was holding open.

    Best effort by design: the record this follows is already terminal and
    durable, so a replay that cannot finish must not reverse it. A run that
    still cannot close simply stays settling and reports through its own
    recovery notice.
    """
    if _settling.get():
        return
    from yoke_core.domain.deployment_run_auto_completion import (
        continue_after_settlement,
    )

    for run_id in settling_runs_for_item(conn, item_id=int(item_id)):
        try:
            continue_after_settlement(conn, run_id)
        except Exception as exc:  # noqa: BLE001 - never reverse a settled record
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 - the notice path reports its own
                pass
            print(
                f"Deployment run {run_id} could not replay settlement after "
                f"item {item_id} cleared: {exc}. Re-drive it under the "
                f"project deploy lock with `yoke deployment-runs update "
                f"{run_id} status succeeded`."
            )


__all__ = [
    "replay_settling_runs_for_item",
    "settlement_in_progress",
    "settling_runs_for_item",
]
