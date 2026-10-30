"""Refresh checklist facts for Overview without treating saved choices as checks.

Deployment supersession records that a project already reached delivery. It
remains separate from current setup_readiness, which requires fresh facts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from yoke_contracts.onboard_checklist import (
    STATUS_BLOCKED,
    STATUS_CONFIGURED,
    STATUS_VERIFIED,
    TERMINAL_STATUSES,
)
from yoke_core.domain.project_onboarding_run_supersede import (
    RUN_STATUS_SUPERSEDED,
    supersede_overtaken_runs,
    superseded_by,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.project_onboarding_runs import get_run
from yoke_core.domain.project_onboarding_schema import _p

RUNS_TABLE = "project_onboarding_runs"
ROWS_TABLE = "project_onboarding_checklist_rows"
ENVIRONMENTS_TABLE = "environments"
STRATEGY_DOCS_TABLE = "strategy_docs"

SCAFFOLD_ROW_ID = "scaffold-install"

#: Scaffold-row statuses that mean a Pack was actually installed. The mapped
#: existing-app ending writes ``not-needed`` instead, and claiming an install
#: there is the copy defect this module exists to remove.
SCAFFOLD_INSTALLED_STATUSES = (STATUS_CONFIGURED, STATUS_VERIFIED)

RUN_STATUS_BLOCKED = STATUS_BLOCKED
RUN_STATUS_COMPLETE = "complete"
RUN_STATUS_OPEN = "open"

#: Run statuses under which the module's checklist is finished.
FINISHED_RUN_STATUSES = (RUN_STATUS_COMPLETE, RUN_STATUS_SUPERSEDED)


def read_onboard_progress(conn: Any) -> Optional[Dict[str, Any]]:
    """The most recent onboarding run's live facts, or ``None`` for none.

    One run drives both the module's state and its copy, so an activated
    card and the progress under it always describe the same run.
    """
    if not (_table_exists(conn, RUNS_TABLE) and _table_exists(conn, ROWS_TABLE)):
        return None
    supersede_overtaken_runs(conn)
    run = conn.execute(
        f"SELECT run_id, status, metadata_json FROM {RUNS_TABLE} "
        "ORDER BY updated_at DESC, run_id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return None
    superseded = superseded_by(run[2]) if str(run[1]) == RUN_STATUS_SUPERSEDED else None
    if superseded:
        return _historical_progress(conn, str(run[0]), superseded)
    current = get_run(str(run[0]), conn=conn)
    rows = current["rows"]
    open_rows = [row for row in rows if row["status"] not in TERMINAL_STATUSES]
    blocked = [row for row in rows if row["status"] == STATUS_BLOCKED]
    action = current["next_action"]
    return {
        "run_status": _run_status(rows, open_rows, blocked),
        "superseded_by": None,
        "setup_readiness": current["setup_readiness"],
        "steps_done": len(rows) - len(open_rows),
        "steps_total": len(rows),
        "next": (
            {
                "step": next(
                    row["step"] for row in rows if row["row_id"] == action["row_id"]
                ),
                "title": action["title"],
            }
            if action
            else None
        ),
        "blocker": _blocker(blocked[0]) if blocked else None,
        "scaffold_installed": any(
            row["row_id"] == SCAFFOLD_ROW_ID
            and row["status"] in SCAFFOLD_INSTALLED_STATUSES
            for row in rows
        ),
        "strategy_docs": _strategy_docs_exist(conn),
        "environments": _environment_names(conn),
    }


def _historical_progress(conn: Any, run_id: str, superseded: Mapping[str, Any]) -> dict:
    """Delivery history does not require today's setup checklist contract."""
    rows = conn.execute(
        f"SELECT row_id, status FROM {ROWS_TABLE} WHERE run_id = {_p(conn)}",
        (run_id,),
    ).fetchall()
    return {
        "run_status": RUN_STATUS_SUPERSEDED,
        "superseded_by": superseded,
        "setup_readiness": {"ready": False, "unmet_rows": []},
        "steps_done": sum(row[1] in TERMINAL_STATUSES for row in rows),
        "steps_total": len(rows),
        "next": None,
        "blocker": None,
        "scaffold_installed": any(
            row[0] == SCAFFOLD_ROW_ID and row[1] in SCAFFOLD_INSTALLED_STATUSES
            for row in rows
        ),
        "strategy_docs": _strategy_docs_exist(conn),
        "environments": _environment_names(conn),
    }


def run_is_complete(progress: Optional[Mapping[str, Any]]) -> bool:
    """Whether *progress* describes a finished checklist.

    Finished means nothing left open, or a run its project's deployments
    superseded.
    """
    return bool(progress) and progress["run_status"] in FINISHED_RUN_STATUSES


def _run_status(
    rows: List[Dict[str, str]],
    open_rows: List[Dict[str, str]],
    blocked: List[Dict[str, str]],
) -> str:
    """A run with no rows at all is open, never complete by vacuum."""
    if blocked:
        return RUN_STATUS_BLOCKED
    return RUN_STATUS_COMPLETE if rows and not open_rows else RUN_STATUS_OPEN


def _step(row: Mapping[str, str]) -> Dict[str, str]:
    return {"step": row["step"], "title": row["title"]}


def _blocker(row: Mapping[str, str]) -> Dict[str, str]:
    return {**_step(row), "detail": row["blocker"]}


def _strategy_docs_exist(conn: Any) -> bool:
    if not _table_exists(conn, STRATEGY_DOCS_TABLE):
        return False
    row = conn.execute(
        f"SELECT EXISTS(SELECT 1 FROM {STRATEGY_DOCS_TABLE} WHERE archived_at IS NULL)"
    ).fetchone()
    return bool(row[0]) if row is not None else False


def _environment_names(conn: Any) -> List[str]:
    """Registered environment names, so the card names what exists."""
    if not _table_exists(conn, ENVIRONMENTS_TABLE):
        return []
    return [
        str(row[0])
        for row in conn.execute(
            f"SELECT DISTINCT name FROM {ENVIRONMENTS_TABLE} "
            "WHERE name IS NOT NULL ORDER BY name"
        ).fetchall()
    ]


__all__ = [
    "ENVIRONMENTS_TABLE",
    "FINISHED_RUN_STATUSES",
    "ROWS_TABLE",
    "RUNS_TABLE",
    "RUN_STATUS_BLOCKED",
    "RUN_STATUS_COMPLETE",
    "RUN_STATUS_OPEN",
    "SCAFFOLD_INSTALLED_STATUSES",
    "SCAFFOLD_ROW_ID",
    "STRATEGY_DOCS_TABLE",
    "read_onboard_progress",
    "run_is_complete",
]
