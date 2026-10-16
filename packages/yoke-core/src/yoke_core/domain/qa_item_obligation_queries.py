"""Read the current effective blocking obligations carried by one item."""

from __future__ import annotations
from typing import Any, TYPE_CHECKING
from yoke_core.domain import db_backend
from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run


if TYPE_CHECKING:
    from yoke_core.domain.deployment_qa_source_obligation import UnsatisfiedBlocking


def unsatisfied_blocking(
    conn: Any, *, item_id: int, target_status: str
) -> UnsatisfiedBlocking:
    """Which of the item's blocking requirements are still unsatisfied.

    At ``done`` each row is answered by :func:`row_unsatisfied_at_done`.
    Item-bound and member-scoped run-bound rows share
    :meth:`GateTarget.where_clause`; admitted copies are not independent.
    """
    return unsatisfied_blocking_many(
        conn, item_ids=(item_id,), target_status=target_status
    )[int(item_id)]


def unsatisfied_blocking_many(
    conn: Any, *, item_ids, target_status: str
) -> dict[int, UnsatisfiedBlocking]:
    """The canonical item scan over a bounded set, without materialization."""
    ids = tuple(dict.fromkeys(int(value) for value in item_ids))
    if not ids:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    holes = ",".join(marker for _ in ids)
    fetched = conn.execute(
        "SELECT qr.* FROM qa_requirements qr "
        f"WHERE (qr.item_id IN ({holes}) OR qr.deployment_member_item_id IN ({holes})) "
        "AND qr.blocking_mode = 'blocking' AND qr.waived_at IS NULL "
        f"AND {unretracted_requirement_sql(conn, 'qr')}",
        (*ids, *ids),
    ).fetchall()
    by_item = {item_id: [] for item_id in ids}
    for raw in fetched:
        row = dict(raw)
        for item_id in {row.get("item_id"), row.get("deployment_member_item_id")}:
            if item_id in by_item:
                by_item[item_id].append(row)
    return {
        item_id: _score(conn, rows, item_id=item_id, target_status=target_status)
        for item_id, rows in by_item.items()
    }


def _score(conn, fetched, *, item_id: int, target_status: str) -> UnsatisfiedBlocking:
    from yoke_core.domain.deployment_qa_source_obligation import (
        UnsatisfiedBlocking,
        row_unsatisfied_at_done,
    )
    from yoke_core.domain.qa_obligation_settlement import (
        effective_obligations,
        obligation_settled,
    )
    from yoke_core.domain.qa_gate_definitions import (
        independent_item_obligation,
        status_settles_blocking_qa,
    )

    scored = []
    for item in effective_obligations(conn, [dict(row) for row in fetched]):
        if obligation_settled(item) or not independent_item_obligation(item):
            continue
        item["passed"] = (
            False
            if item.get("replacement_graph_error")
            else has_current_passing_run(conn, int(item["id"]))
        )
        scored.append(item)
    if status_settles_blocking_qa(target_status):
        unsatisfied = [
            row
            for row in scored
            if row.get("replacement_graph_error")
            or row_unsatisfied_at_done(conn, row, item_id=int(item_id))
        ]
    else:
        unsatisfied = [row for row in scored if not row["passed"]]
    return UnsatisfiedBlocking(
        count=len(unsatisfied),
        includes_post_deploy=any(
            str(row["qa_phase"] or "") == "post_deploy" for row in unsatisfied
        ),
        rows=tuple(unsatisfied),
    )
