"""Bring a frozen source-bound plan forward to the cases its own release carries.

A run freezes each selected plan's cases when it starts. Boot convergence and
``qa.plan_cases.sync`` move a source-bound plan only after its build merges,
which for a release is usually after the run froze. Before a stage first
materializes the plan, the frozen contract yields to the saved plan when the
saved source descends from the frozen source and the run's candidate carries
it, so a release ships the code-authored cases its build adds. Any refusal keeps
the frozen cases, which remain a valid contract for the candidate.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSourceUnavailable,
    open_carried_work_source,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_source_revision import (
    current_plan_source,
    require_candidate_plan,
    require_forward_source,
)

_log = logging.getLogger(__name__)

#: Transient key carrying the complete refreshed contract to the writeback.
REFRESHED_CONTRACT = "refreshed_contract"


def source_refreshed_plan(
    conn: Any,
    subject: Mapping[str, Any],
    value: dict[str, Any],
    *,
    materialized: Callable[[], set[int]],
) -> dict[str, Any]:
    """Return ``value`` with the saved plan's cases, or unchanged when it must hold.

    ``materialized`` names plans this stage already turned into requirements;
    their acceptance stays with the contract they were materialized from. The
    saved plan is read without a row lock, because read paths call this too;
    a sync landing between its plan and case reads keeps the frozen cases.
    """
    plan = value["plan"]
    plan_id = int(plan["id"])
    frozen = plan.get("source_revision")
    if not frozen:
        return value
    current = current_plan_source(conn, plan_id)
    if not current or current == frozen or plan_id in materialized():
        return value
    project_id = int(plan["project_id"])
    try:
        live = _plan_snapshot(conn, plan_id, project_id=project_id, lock_plan=False)
        revision = str(live["plan"]["source_revision"])
        settled = query_scalar(
            conn, "SELECT source_revision FROM qa_plans WHERE id=%s", (plan_id,)
        )
        if settled != revision:
            raise ValueError(
                f"the saved plan moved to source {settled} while it was read; "
                "the next QA read refreshes it"
            )
        require_forward_source(
            open_carried_work_source(conn, project_id), str(frozen), revision
        )
        require_candidate_plan(conn, live["plan"], str(subject["id"]))
    except (
        CarriedWorkSourceUnavailable,
        LookupError,
        OSError,
        QaPlanError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        _log.warning(
            "qa_frozen_plan_kept: run %s stage %s keeps plan %s (%s) at frozen "
            "source %s instead of saved source %s. Reason: %s. The frozen cases "
            "are materialized; release a candidate carrying the saved source to "
            "run its cases.",
            subject["id"],
            subject["stage"]["name"],
            plan_id,
            plan.get("slug"),
            frozen,
            current,
            exc,
        )
        return value
    _log.info(
        "qa_frozen_plan_refreshed: run %s stage %s uses plan %s (%s) at source "
        "%s, which descends from frozen source %s and the candidate carries.",
        subject["id"],
        subject["stage"]["name"],
        plan_id,
        plan.get("slug"),
        revision,
        frozen,
    )
    return {**value, **live, REFRESHED_CONTRACT: live}


__all__ = ["REFRESHED_CONTRACT", "source_refreshed_plan"]
