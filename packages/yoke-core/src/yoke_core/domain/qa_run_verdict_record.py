"""The one write path for ``qa_runs`` rows and the verdicts they carry.

A passing verdict does more than add a row: a failed case that declared this
requirement its replacement is discharged by it, on the verdict's own
transaction (:mod:`yoke_core.domain.qa_requirement_replacement`). When that
step lived beside a single writer, every other writer recorded a pass the
stage gate kept reading as blocked, because the failed row it replaced was
never superseded. Every insert and every verdict-setting update therefore
goes through this module, so no writer can record a pass without its
discharge. The supersession columns are the durable record of a discharge;
telemetry for it is optional and belongs to callers that announce after
their commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from typing import Any

from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.qa_requirement_scope import lock_requirement_scope

PASS_VERDICT = "pass"


@dataclass(frozen=True)
class QaRunWrite:
    """The written run and the failed rows its pass discharged."""

    run_id: int
    discharged: list[tuple[dict[str, Any], dict[str, Any]]] = field(
        default_factory=list
    )


def _discharge_on_pass(
    conn: Any, requirement_id: int, run_id: int, verdict: Any
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if verdict != PASS_VERDICT:
        return []
    from yoke_core.domain.schema_common import _column_exists

    if not _column_exists(conn, "qa_requirements", "replacement_requirement_id"):
        return []
    if (
        conn.execute(
            "SELECT id FROM qa_requirements WHERE replacement_requirement_id=%s "
            "AND superseded_by_requirement_id IS NULL LIMIT 1",
            (int(requirement_id),),
        ).fetchone()
        is None
    ):
        return []
    from yoke_core.domain.qa_latest_execution import latest_executions

    current = latest_executions(conn, [requirement_id]).get(requirement_id)
    if current is None or int(current["id"]) != run_id:
        return []
    from yoke_core.domain.qa_requirement_replacement import (
        discharge_declared_replacements,
    )

    return discharge_declared_replacements(conn, [int(requirement_id)])


def _clock_columns(conn: Any, columns: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize declared run clocks before locks or writes; other data is opaque."""
    result = dict(columns)
    for name in ("started_at", "completed_at", "created_at"):
        if name in result:
            value = result[name]
            instant = (
                None if value is None and name != "created_at" else parse_instant(value)
            )
            result[name] = instant_parameter(conn, instant)
    return result


def insert_qa_run(conn: Any, **columns: Any) -> QaRunWrite:
    """Insert one run on the caller's transaction; a pass discharges its replacements."""
    columns = _clock_columns(conn, columns)
    lock_requirement_scope(conn, int(columns["qa_requirement_id"]))
    p = marker(conn)
    names = list(columns)
    row = conn.execute(
        f"INSERT INTO qa_runs({','.join(names)}) "
        f"VALUES({','.join([p] * len(names))}) RETURNING id",
        tuple(columns.values()),
    ).fetchone()
    run_id = int(row["id"] if hasattr(row, "keys") else row[0])
    return QaRunWrite(
        run_id,
        _discharge_on_pass(
            conn, int(columns["qa_requirement_id"]), run_id, columns.get("verdict")
        ),
    )


def update_qa_run(
    conn: Any,
    run_id: int,
    columns: Mapping[str, Any],
    *,
    unjudged_only: bool = False,
    default_completed_at: datetime | str | None = None,
) -> QaRunWrite:
    """Update one run on the caller's transaction; a pass discharges its replacements.

    ``unjudged_only`` leaves a run that already carries a verdict untouched;
    ``default_completed_at`` fills ``completed_at`` only where it is empty.
    """
    columns = _clock_columns(conn, columns)
    if default_completed_at is not None:
        default_completed_at = instant_parameter(
            conn, parse_instant(default_completed_at)
        )
    p = marker(conn)
    subject = conn.execute(
        f"SELECT qa_requirement_id FROM qa_runs WHERE id={p}", (int(run_id),)
    ).fetchone()
    if subject is not None:
        lock_requirement_scope(conn, int(subject[0]))
    assignments = [f"{name}={p}" for name in columns]
    params: list[Any] = list(columns.values())
    if default_completed_at is not None:
        assignments.append(f"completed_at=COALESCE(completed_at,{p})")
        params.append(default_completed_at)
    sql = f"UPDATE qa_runs SET {','.join(assignments)} WHERE id={p}"
    params.append(int(run_id))
    if unjudged_only:
        sql += " AND verdict IS NULL"
    cursor = conn.execute(sql, tuple(params))
    if not getattr(cursor, "rowcount", 1) or columns.get("verdict") != PASS_VERDICT:
        return QaRunWrite(int(run_id))
    requirement = conn.execute(
        f"SELECT qa_requirement_id FROM qa_runs WHERE id={p}", (int(run_id),)
    ).fetchone()
    requirement_id = (
        requirement["qa_requirement_id"]
        if hasattr(requirement, "keys")
        else requirement[0]
    )
    return QaRunWrite(
        int(run_id),
        _discharge_on_pass(conn, int(requirement_id), int(run_id), PASS_VERDICT),
    )


__all__ = ["PASS_VERDICT", "QaRunWrite", "insert_qa_run", "update_qa_run"]
