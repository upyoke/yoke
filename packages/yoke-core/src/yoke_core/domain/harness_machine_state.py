"""Read and upsert per-project harness machine reports."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import _table_exists


APPROVAL_STATES = frozenset(
    {"approved", "unapproved", "not_applicable", "unknown"}
)


def read_harness_machine_reports(conn: Any) -> list[dict[str, Any]]:
    """Return every stored machine report, or empty when the table is absent."""
    if not _table_exists(conn, "harness_machine_reports"):
        return []
    rows = conn.execute(
        "SELECT project_id, harness_id, glue_written, glue_present, "
        "glue_malformed, config_present, project_entry_present, "
        "approval_state, reported_at FROM harness_machine_reports"
    ).fetchall()
    return [
        {
            "project_id": int(row[0]),
            "harness_id": str(row[1]),
            "glue_written": bool(row[2]),
            "glue_present": bool(row[3]),
            "glue_malformed": bool(row[4]),
            "config_present": bool(row[5]),
            "project_entry_present": bool(row[6]),
            "approval_state": str(row[7]),
            "reported_at": row[8],
        }
        for row in rows
    ]


def upsert_harness_machine_reports(
    conn: Any,
    *,
    project_id: int,
    reports: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Replace the project's reports with ``reports`` and return the stored rows."""
    from yoke_core.domain.harness_machine_schema import ensure_harness_machine_schema

    ensure_harness_machine_schema(conn, commit=False)
    now = iso8601_now()
    stored: list[dict[str, Any]] = []
    for raw in reports:
        harness_id = str(raw.get("harness_id") or "").strip().lower()
        if not harness_id:
            raise ValueError("each report requires harness_id")
        approval = str(raw.get("approval_state") or "unknown")
        if approval not in APPROVAL_STATES:
            raise ValueError(f"unknown approval_state {approval!r}")
        row = {
            "project_id": int(project_id),
            "harness_id": harness_id,
            "glue_written": 1 if raw.get("glue_written") else 0,
            "glue_present": 1 if raw.get("glue_present") else 0,
            "glue_malformed": 1 if raw.get("glue_malformed") else 0,
            "config_present": 1 if raw.get("config_present") else 0,
            "project_entry_present": 1 if raw.get("project_entry_present") else 0,
            "approval_state": approval,
            "reported_at": now,
        }
        conn.execute(
            "INSERT INTO harness_machine_reports ("
            "project_id, harness_id, glue_written, glue_present, "
            "glue_malformed, config_present, project_entry_present, "
            "approval_state, reported_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (project_id, harness_id) DO UPDATE SET "
            "glue_written=EXCLUDED.glue_written, "
            "glue_present=EXCLUDED.glue_present, "
            "glue_malformed=EXCLUDED.glue_malformed, "
            "config_present=EXCLUDED.config_present, "
            "project_entry_present=EXCLUDED.project_entry_present, "
            "approval_state=EXCLUDED.approval_state, "
            "reported_at=EXCLUDED.reported_at",
            (
                row["project_id"],
                row["harness_id"],
                row["glue_written"],
                row["glue_present"],
                row["glue_malformed"],
                row["config_present"],
                row["project_entry_present"],
                row["approval_state"],
                row["reported_at"],
            ),
        )
        stored.append({**row, "glue_written": bool(row["glue_written"]),
                       "glue_present": bool(row["glue_present"]),
                       "glue_malformed": bool(row["glue_malformed"]),
                       "config_present": bool(row["config_present"]),
                       "project_entry_present": bool(row["project_entry_present"])})
    conn.commit()
    return stored


__all__ = [
    "APPROVAL_STATES",
    "read_harness_machine_reports",
    "upsert_harness_machine_reports",
]
