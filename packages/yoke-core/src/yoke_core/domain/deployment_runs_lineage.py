"""Lineage helpers for deployment runs.

Owns: ``cmd_lineage`` (sibling-run lookup by ``release_lineage``),
``cmd_lineage_create`` (generate next lineage ID),
``cmd_lineage_final_status`` (final-target run status for a lineage).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.deployment_runs_schema import _pipe_rows, _run_select


def cmd_lineage(run_id: str, db_path: Optional[str] = None) -> Optional[str]:
    """Return all runs sharing same release_lineage. Returns None if no lineage."""
    conn = connect(db_path)
    try:
        lineage = query_scalar(
            conn,
            "SELECT release_lineage FROM deployment_runs WHERE id=%s",
            (run_id,),
        )
        if not lineage:
            return None

        rows = query_rows(
            conn,
            f"SELECT {_run_select(conn)} FROM deployment_runs WHERE release_lineage=%s ORDER BY created_at ASC",
            (lineage,),
        )
        return _pipe_rows(rows)
    finally:
        conn.close()


def cmd_lineage_create(db_path: Optional[str] = None) -> str:
    """Generate a new lineage ID (lineage-YYYYMMDD-NNN)."""
    conn = connect(db_path)
    try:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        prefix = f"lineage-{today}-"
        # deliberate case-sensitive match against internal lineage-id prefix
        count = query_scalar(
            conn,
            "SELECT COUNT(DISTINCT release_lineage) FROM deployment_runs WHERE release_lineage LIKE %s",
            (f"{prefix}%",),
        )
        next_num = (count or 0) + 1
        return f"{prefix}{next_num:03d}"
    finally:
        conn.close()


def cmd_lineage_final_status(lineage_id: str, db_path: Optional[str] = None) -> str:
    """Status of last production-target run in lineage. Returns 'none' if not found."""
    from yoke_core.domain.environment_delivery_record import PRODUCTION_ENV_NAME

    conn = connect(db_path)
    try:
        run_status = query_scalar(
            conn,
            "SELECT dr.status FROM deployment_runs dr "
            "JOIN environments e ON e.id = dr.target_environment_id "
            "WHERE dr.release_lineage=%s AND e.name=%s "
            "ORDER BY dr.created_at DESC LIMIT 1",
            (lineage_id, PRODUCTION_ENV_NAME),
        )
        return run_status if run_status else "none"
    finally:
        conn.close()
