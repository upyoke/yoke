"""Deployment-run lookup and stage-advancement semantics.

This module owns the Python domain logic for deployment runs: looking up
active runs for items, advancing run stages, and validating run state
transitions.

Schema reference (deployment_runs table):
- id: TEXT PRIMARY KEY
- project_id, flow, target_env, release_lineage, status, current_stage
- status CHECK IN ('created','executing','succeeded','failed','cancelled')
- created_at, started_at, completed_at, created_by

Schema reference (deployment_run_items junction table):
- run_id + item_id composite PK (no standalone id column)
- added_at

All constants and functions here MUST remain aligned with the current DB
schema. The canonical CLI surface is ``python3 -m yoke_core.cli.db_router runs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Run status enum
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    """Canonical deployment run statuses.

    Source of truth: deployment_runs CHECK constraint.
    """

    CREATED = "created"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Runs in these statuses are considered "active" (not yet terminated).
ACTIVE_RUN_STATUSES = frozenset({RunStatus.CREATED.value, RunStatus.EXECUTING.value})

# Runs in these statuses are considered "terminal" (completed in some way).
TERMINAL_RUN_STATUSES = frozenset({
    RunStatus.SUCCEEDED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
})

# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeploymentRun:
    """Lightweight representation of a deployment run row."""

    id: str
    project: str
    flow: str
    status: str
    current_stage: Optional[str] = None
    target_env: Optional[str] = None
    release_lineage: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_by: str = "operator"


@dataclass(frozen=True)
class RunItem:
    """A member item in a deployment run."""

    run_id: str
    item_id: int
    added_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Run-status validation
# ---------------------------------------------------------------------------


def is_valid_run_status(status: str) -> bool:
    """Return True if *status* is a valid deployment run status."""
    try:
        RunStatus(status)
        return True
    except ValueError:
        return False


def is_active_run(status: str) -> bool:
    """Return True if a run with this status is still active (not terminal)."""
    return status in ACTIVE_RUN_STATUSES


def is_terminal_run(status: str) -> bool:
    """Return True if a run with this status is terminal."""
    return status in TERMINAL_RUN_STATUSES


# ---------------------------------------------------------------------------
# Active-run lookup logic
# ---------------------------------------------------------------------------


def find_active_run_for_item(
    runs: Sequence[DeploymentRun],
) -> Optional[DeploymentRun]:
    """Given a sequence of runs associated with an item, return the most
    recent active (non-terminal) run, or ``None``.

    Runs are expected to be ordered by ``created_at DESC`` (most recent first).
    This mirrors the SQL pattern used in main.py's approve endpoint and
    ``yoke-db.sh runs find-by-item``.
    """
    for run in runs:
        if is_active_run(run.status):
            return run
    return None


def item_has_active_run(runs: Sequence[DeploymentRun]) -> bool:
    """Return True if any run in the sequence is active."""
    return find_active_run_for_item(runs) is not None


# ---------------------------------------------------------------------------
# Stage advancement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageAdvancement:
    """Result of attempting to advance a deployment run's stage.

    Attributes:
        advanced: True if the advancement is valid.
        next_stage: The stage name the run should move to.
            ``"complete"`` if advancing past the last stage.
        run_id: The run being advanced.
        error: Human-readable error if advancement failed.
    """

    advanced: bool
    next_stage: Optional[str] = None
    run_id: Optional[str] = None
    error: Optional[str] = None


def advance_run_stage(
    run: DeploymentRun,
    flow_stages_names: Sequence[str],
) -> StageAdvancement:
    """Determine the next stage for a deployment run.

    Validates:
    1. The run is active (not terminal).
    2. The run's current_stage exists in the flow.

    Returns a ``StageAdvancement`` with ``advanced=True`` and the next
    stage name, or ``advanced=False`` with an error.
    """
    if not is_active_run(run.status):
        return StageAdvancement(
            advanced=False,
            run_id=run.id,
            error=f"Run '{run.id}' is in terminal status '{run.status}'. Cannot advance.",
        )

    if run.current_stage is None:
        # A run with no current_stage: advance to the first stage
        if not flow_stages_names:
            return StageAdvancement(
                advanced=False,
                run_id=run.id,
                error=f"Run '{run.id}' has no current_stage and the flow has no stages.",
            )
        return StageAdvancement(
            advanced=True,
            next_stage=flow_stages_names[0],
            run_id=run.id,
        )

    # Find current stage in the flow
    try:
        current_idx = list(flow_stages_names).index(run.current_stage)
    except ValueError:
        return StageAdvancement(
            advanced=False,
            run_id=run.id,
            error=(
                f"Run '{run.id}' current_stage '{run.current_stage}' "
                f"does not match any stage in the flow."
            ),
        )

    # Advance to next stage or complete
    if current_idx + 1 < len(flow_stages_names):
        return StageAdvancement(
            advanced=True,
            next_stage=flow_stages_names[current_idx + 1],
            run_id=run.id,
        )

    return StageAdvancement(
        advanced=True,
        next_stage="complete",
        run_id=run.id,
    )


# ---------------------------------------------------------------------------
# SQL fragment helpers for run filtering
# ---------------------------------------------------------------------------


def sql_active_run_statuses() -> str:
    """Return SQL IN-clause fragment for active run statuses."""
    return "'created','executing'"


def sql_terminal_run_statuses() -> str:
    """Return SQL IN-clause fragment for terminal run statuses."""
    return "'succeeded','failed','cancelled'"


def sql_active_run_exists_for_item(item_id_col: str = "i.id") -> str:
    """Return a SQL EXISTS subquery that checks for an active deployment run.

    The *item_id_col* is the SQL column reference for the item ID in the
    outer query (default: ``i.id``).
    """
    return (
        f"EXISTS ("
        f"SELECT 1 FROM deployment_run_items dri "
        f"JOIN deployment_runs dr ON dr.id = dri.run_id "
        f"WHERE dri.item_id = {item_id_col} "
        f"AND dr.status = 'executing'"
        f")"
    )
