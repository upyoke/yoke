"""Failure signals that paint a session card's item stage strip red."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.qa_constants import VALID_VERDICTS
from yoke_core.domain.schema_common import _table_exists


_FAIL_VERDICTS = tuple(
    verdict for verdict in VALID_VERDICTS if verdict in {"fail", "error"}
)
_LAUNCH_FAILURE_STATES = frozenset({"expired", "failed", "outcome_unknown"})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def qa_failures(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    """The transition whose latest QA run failed, per item."""
    if not item_ids or not all(
        _table_exists(conn, name) for name in ("qa_requirements", "qa_runs")
    ):
        return {}
    marker = _p(conn)
    fail_markers = ",".join(marker for _ in _FAIL_VERDICTS)
    records = conn.execute(
        "SELECT item_id,workflow_transition_id,run_id FROM ("
        "SELECT q.item_id,q.workflow_transition_id,r.id AS run_id,r.verdict,"
        "ROW_NUMBER() OVER (PARTITION BY q.id ORDER BY r.id DESC) AS row_num "
        "FROM qa_requirements q JOIN qa_runs r ON r.qa_requirement_id=q.id "
        "WHERE q.item_id IN ("
        + ",".join(marker for _ in item_ids)
        + ")) latest WHERE row_num=1 AND verdict IN ("
        + fail_markers
        + ") ORDER BY run_id DESC",
        (*item_ids, *_FAIL_VERDICTS),
    ).fetchall()
    failures: dict[int, str] = {}
    for record in records:
        failures.setdefault(
            int(record["item_id"]),
            str(record["workflow_transition_id"] or ""),
        )
    return failures


def merge_failures(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    """The label of the newest unresolved merge failure, per item.

    Read from the merge receipt each item owns, which records the failure a
    merge attempt ended on and drops it once a merge on that identity lands.
    The strip therefore paints what the merge is doing now, rather than a
    state reconstructed from the order telemetry happened to arrive in.
    """
    from yoke_core.domain.item_merge_receipt_document import current_failures

    if not item_ids:
        return {}
    return current_failures(conn, item_ids)


def launch_failures(
    conn: Any,
    items: Mapping[int, Mapping[str, Any]],
) -> dict[int, str]:
    """Items whose newest named session launch did not come up."""
    if not items or not _table_exists(conn, "session_launches"):
        return {}
    project_ids = tuple(
        dict.fromkeys(int(item["project_id"]) for item in items.values())
    )
    marker = _p(conn)
    records = conn.execute(
        "SELECT project_id,session_name,state FROM session_launches "
        "WHERE project_id IN ("
        + ",".join(marker for _ in project_ids)
        + ") ORDER BY created_at DESC,launch_id DESC",
        project_ids,
    ).fetchall()
    by_ref = {
        (int(item["project_id"]), str(item["public_ref"])): item_id
        for item_id, item in items.items()
    }
    observed: set[int] = set()
    failures: dict[int, str] = {}
    for record in records:
        public_ref = str(record["session_name"] or "").partition(":")[0]
        item_id = by_ref.get((int(record["project_id"]), public_ref))
        if item_id is None or item_id in observed:
            continue
        observed.add(item_id)
        if str(record["state"] or "") in _LAUNCH_FAILURE_STATES:
            failures[item_id] = "launch failed"
    return failures


__all__ = ["launch_failures", "merge_failures", "qa_failures"]
