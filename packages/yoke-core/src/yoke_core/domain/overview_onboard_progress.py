"""Live checklist facts behind the Overview's ``/yoke onboard`` module.

The module's state and its every rendered sentence come from here, because
the fact a member needs is not "did somebody start onboarding" but "how far
did it get, and what is it stuck on". A run row appears the moment the skill
opens its checklist, so existence alone is satisfied while nothing has been
configured yet; completion is what the module claims, and completion means a
checklist with no open rows.

Nothing is latched here. The activation latch is monotone and reads only the
completion verdict; these facts re-derive on every read so a card can name
the blocker a run picked up after it activated.

The three outcome flags exist because a complete run does not imply a
particular ending: a mapped existing app finishes with the scaffold row
``not-needed`` and installs nothing, and a run may finish having deferred
its environments. The card claims each outcome only where the universe
carries its registration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from yoke_contracts.onboard_checklist import (
    ROW_SPECS,
    STATUS_BLOCKED,
    STATUS_CONFIGURED,
    STATUS_VERIFIED,
    TERMINAL_STATUSES,
)
from yoke_core.domain.schema_common import _table_exists

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

#: Checklist position comes from the contract's row order, never from the
#: ``step`` label: the labels sort "1", "10", "17a", "9a" as text, which
#: would name the wrong next step.
_ROW_ORDER = {spec.row_id: index for index, spec in enumerate(ROW_SPECS)}


def read_onboard_progress(conn: Any) -> Optional[Dict[str, Any]]:
    """The most recent onboarding run's live facts, or ``None`` for none.

    One run drives both the module's state and its copy, so an activated
    card and the progress under it always describe the same run.
    """
    if not (_table_exists(conn, RUNS_TABLE) and _table_exists(conn, ROWS_TABLE)):
        return None
    run = conn.execute(
        f"SELECT run_id FROM {RUNS_TABLE} "
        "ORDER BY updated_at DESC, run_id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        return None
    rows = _ordered_rows(conn, str(run[0]))
    open_rows = [row for row in rows if row["status"] not in TERMINAL_STATUSES]
    blocked = [row for row in rows if row["status"] == STATUS_BLOCKED]
    return {
        "run_status": _run_status(rows, open_rows, blocked),
        "steps_done": len(rows) - len(open_rows),
        "steps_total": len(rows),
        "next": _step(open_rows[0]) if open_rows else None,
        "blocker": _blocker(blocked[0]) if blocked else None,
        "scaffold_installed": any(
            row["row_id"] == SCAFFOLD_ROW_ID
            and row["status"] in SCAFFOLD_INSTALLED_STATUSES
            for row in rows
        ),
        "strategy_docs": _strategy_docs_exist(conn),
        "environments": _environment_names(conn),
    }


def run_is_complete(progress: Optional[Mapping[str, Any]]) -> bool:
    """Whether *progress* describes a checklist with nothing left open."""
    return bool(progress) and progress["run_status"] == RUN_STATUS_COMPLETE


def _run_status(
    rows: List[Dict[str, str]],
    open_rows: List[Dict[str, str]],
    blocked: List[Dict[str, str]],
) -> str:
    """A run with no rows at all is open, never complete by vacuum."""
    if blocked:
        return RUN_STATUS_BLOCKED
    return RUN_STATUS_COMPLETE if rows and not open_rows else RUN_STATUS_OPEN


def _ordered_rows(conn: Any, run_id: str) -> List[Dict[str, str]]:
    rows = conn.execute(
        f"SELECT row_id, step, title, status, blocker FROM {ROWS_TABLE} "
        "WHERE run_id = %s",
        (run_id,),
    ).fetchall()
    payloads = [
        {
            "row_id": str(row[0]),
            "step": str(row[1]),
            "title": str(row[2]),
            "status": str(row[3]),
            "blocker": str(row[4] or ""),
        }
        for row in rows
    ]
    return sorted(
        payloads,
        key=lambda row: (
            _ROW_ORDER.get(row["row_id"], len(_ROW_ORDER)),
            row["row_id"],
        ),
    )


def _step(row: Mapping[str, str]) -> Dict[str, str]:
    return {"step": row["step"], "title": row["title"]}


def _blocker(row: Mapping[str, str]) -> Dict[str, str]:
    return {**_step(row), "detail": row["blocker"]}


def _strategy_docs_exist(conn: Any) -> bool:
    if not _table_exists(conn, STRATEGY_DOCS_TABLE):
        return False
    row = conn.execute(
        f"SELECT EXISTS(SELECT 1 FROM {STRATEGY_DOCS_TABLE} "
        "WHERE archived_at IS NULL)"
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
