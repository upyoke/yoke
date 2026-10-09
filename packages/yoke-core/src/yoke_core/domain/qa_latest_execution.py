"""Select actual QA attempts by their start instant, before grading evidence."""

from datetime import datetime
from typing import Any, Iterable

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows


def actual_execution_sql(alias: str) -> str:
    """Durable review associations identify historical judgment-only rows.

    A self-reference is a judgment attached to a real capture. Runner labels
    cannot classify executions: a real agent attempt remains eligible.
    """
    return (
        "NOT EXISTS (SELECT 1 FROM qa_plan_review_verdicts judgment "
        "JOIN qa_runs capture ON capture.id=judgment.capture_run_id "
        f"WHERE judgment.review_run_id={alias}.id "
        f"AND judgment.requirement_id={alias}.qa_requirement_id "
        f"AND capture.qa_requirement_id={alias}.qa_requirement_id "
        "AND judgment.capture_run_id <> judgment.review_run_id)"
    )


def latest_execution_id_sql(requirement_id: str) -> str:
    """Newest actual start, with id breaking equal starts, on PostgreSQL.

    Starts are native instants. NULL starts sort first so an
    ambiguous attempt cannot be hidden by an older passing attempt.
    """
    return (
        "SELECT latest.id FROM qa_runs latest "
        f"WHERE latest.qa_requirement_id = {requirement_id} "
        f"AND {actual_execution_sql('latest')} "
        "ORDER BY latest.started_at DESC NULLS FIRST, "
        "latest.id DESC LIMIT 1"
    )


def execution_start(run: dict[str, Any]) -> datetime:
    """Require authoritative aware start evidence; never invent a fallback."""
    value = run.get("started_at")
    try:
        instant = parse_instant(value)
    except InvalidInstant as exc:
        raise ValueError(
            f"qa_execution_order_ambiguous: run {run['id']} has no valid aware "
            "started_at; correct authoritative start evidence through a registered "
            "correction before grading this requirement"
        ) from exc
    return instant


def latest_executions(
    conn: Any, requirement_ids: Iterable[int]
) -> dict[int, dict[str, Any]]:
    """The current actual attempt for each requirement, including pending rows."""
    ids = tuple(sorted(set(int(value) for value in requirement_ids)))
    if not ids:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = query_rows(
        conn,
        "SELECT run.* FROM qa_runs run WHERE run.qa_requirement_id IN ("
        + ",".join(marker for _ in ids)
        + f") AND {actual_execution_sql('run')}",
        ids,
    )
    return select_latest_executions(rows)


def select_latest_executions(rows: Iterable[Any]) -> dict[int, dict[str, Any]]:
    """Apply the native start/id kernel to actual attempts from one snapshot."""
    selected: dict[int, dict[str, Any]] = {}
    for row in rows:
        run = dict(row)
        key = (execution_start(run), int(run["id"]))
        requirement_id = int(run["qa_requirement_id"])
        prior = selected.get(requirement_id)
        if prior is None or key > (execution_start(prior), int(prior["id"])):
            selected[requirement_id] = run
    return selected


def current_first_run_history(
    rows: Iterable[Any], requirement_id: int | None
) -> list[Any]:
    """Put the native-selected attempt first without discarding audit history.

    Requirement-filtered run lists feed case detail. Detached judgments stay
    readable as history but cannot become the current answer. Unfiltered
    listings retain their existing order and do not grade unrelated cases.
    """
    history = list(rows)
    if requirement_id is None or not history:
        return history
    current = select_latest_executions(
        row for row in history if row["actual_execution"]
    ).get(int(requirement_id))
    if current is None:
        raise ValueError(
            f"qa_execution_order_ambiguous: requirement {requirement_id} has only "
            "judgment audit rows; inspect and correct authoritative capture "
            "associations through the control-plane operator before grading"
        )
    current_id = current["id"]
    return sorted(
        history,
        key=lambda row: (row["id"] == current_id, int(row["id"])),
        reverse=True,
    )
