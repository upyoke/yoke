"""Read and persist completed Doctor runs in ``doctor_runs``.

``doctor.run.run`` writes one receipt row per completed run. This module
is the read behind ``doctor.last_run.get`` and the write helper the run
handler calls. The events journal is telemetry only and is never scanned
here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.doctor_runs_schema import DOCTOR_RUNS_TABLE
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.project_identity import resolve_project, row_value
from yoke_core.domain.schema_common import _table_exists as table_exists


CHECK_RESULT_FIELDS = ("hc", "name", "severity", "detail")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _check_rows(raw: Any) -> List[Dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    return [
        {field: entry.get(field) for field in CHECK_RESULT_FIELDS}
        for entry in rows
        if isinstance(entry, dict)
    ]


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def record_doctor_run(conn: Any, payload: Dict[str, Any]) -> None:
    """Insert one completed-run receipt. Caller supplies an open connection."""
    marker = _p(conn)
    conn.execute(
        f"INSERT INTO {DOCTOR_RUNS_TABLE} ("
        "ran_at, project, scope, runtime, fail_count, pass_count, "
        "warn_count, na_count, results"
        f") VALUES ({marker}, {marker}, {marker}, {marker}, "
        f"{marker}, {marker}, {marker}, {marker}, {marker})",
        (
            str(payload.get("ran_at") or db_helpers.iso8601_now()),
            str(payload.get("project") or ""),
            payload.get("scope"),
            payload.get("runtime"),
            _count(payload.get("fail_count")),
            _count(payload.get("pass_count")),
            _count(payload.get("warn_count")),
            _count(payload.get("na_count")),
            dumps_compact(_check_rows(payload.get("results"))),
        ),
    )
    conn.commit()


def persist_completed_run(conn: Any, served: Dict[str, Any]) -> None:
    """Write one receipt for a completed unpaginated ``doctor.run.run``."""
    record_doctor_run(conn, served)


def record_receipt_from_payload(raw: Any) -> HandlerOutcome:
    """Persist a composed receipt posted as ``doctor.run.run`` payload.receipt."""
    if not isinstance(raw, dict):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="receipt must be an object",
                jsonpath="$.payload.receipt",
            ),
        )
    project = str(raw.get("project") or "").strip()
    if not project:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="receipt.project is required",
                jsonpath="$.payload.receipt.project",
            ),
        )
    conn = db_helpers.connect()
    try:
        record_doctor_run(conn, raw)
    finally:
        conn.close()
    served = {
        "results": _check_rows(raw.get("results")),
        "scope": raw.get("scope"),
        "project": project,
        "runtime": raw.get("runtime"),
        "fail_count": _count(raw.get("fail_count")),
        "warn_count": _count(raw.get("warn_count")),
        "pass_count": _count(raw.get("pass_count")),
        "na_count": _count(raw.get("na_count")),
        "done": True,
    }
    return HandlerOutcome(result_payload=served, primary_success=True)


def _accepted_project_names(conn: Any, project: str) -> Set[str]:
    ident = resolve_project(conn, project)
    if ident is None:
        raise LookupError(f"project {project!r} not found")
    return {ident.slug, str(ident.id)}


def _serve_row(row: Any) -> Dict[str, Any]:
    raw_results = row_value(row, "results", 8) or "[]"
    try:
        parsed = (
            loads_text(raw_results) if isinstance(raw_results, str) else raw_results
        )
    except ValueError:
        parsed = []
    checks = _check_rows(parsed)
    return {
        "never_run": False,
        "ran_at": str(row_value(row, "ran_at", 0) or ""),
        "scope": row_value(row, "scope", 2),
        "project": row_value(row, "project", 1),
        "pass_count": _count(row_value(row, "pass_count", 5)),
        "warn_count": _count(row_value(row, "warn_count", 6)),
        "fail_count": _count(row_value(row, "fail_count", 4)),
        "na_count": _count(row_value(row, "na_count", 7)),
        "total": len(checks),
        "results": checks,
        "truncated": False,
    }


def last_doctor_run(*, project: Optional[str] = None) -> Dict[str, Any]:
    """Serve the newest completed doctor run recorded in ``doctor_runs``."""
    conn = db_helpers.connect()
    try:
        if not table_exists(conn, DOCTOR_RUNS_TABLE):
            return {"never_run": True}
        accepted = _accepted_project_names(conn, project) if project else None
        marker = _p(conn)
        sql = (
            f"SELECT ran_at, project, scope, runtime, fail_count, pass_count, "
            f"warn_count, na_count, results FROM {DOCTOR_RUNS_TABLE}"
        )
        params: List[Any] = []
        if accepted is not None:
            placeholders = ", ".join(marker for _ in accepted)
            sql += f" WHERE project IN ({placeholders})"
            params.extend(sorted(accepted))
        sql += " ORDER BY ran_at DESC, id DESC LIMIT 1"
        row = conn.execute(sql, tuple(params)).fetchone()
        if row is None:
            return {"never_run": True}
        return _serve_row(row)
    finally:
        conn.close()


__all__ = [
    "CHECK_RESULT_FIELDS",
    "last_doctor_run",
    "persist_completed_run",
    "record_doctor_run",
    "record_receipt_from_payload",
]
