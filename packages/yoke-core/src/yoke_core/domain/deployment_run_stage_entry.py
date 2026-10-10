"""Durable stage-entry clocks and pinned stage classification for live runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.schema_common import _column_exists


def set_current_stage(
    conn: Any, run_id: str, stage: str, *, only_executing: bool = False
) -> None:
    """Write the stage and its entry clock together in the caller's transaction.

    Re-driving the same stage preserves its age. Before the additive column
    converges, the stage still advances; readers show an unknown age rather
    than guessing from another clock. No old run is backfilled.
    """
    guard = " AND status='executing'" if only_executing else ""
    if _column_exists(conn, "deployment_runs", "current_stage_entered_at"):
        conn.execute(
            "UPDATE deployment_runs SET current_stage_entered_at=CASE "
            "WHEN current_stage IS DISTINCT FROM %s THEN %s "
            f"ELSE current_stage_entered_at END,current_stage=%s WHERE id=%s{guard}",
            (stage, instant_parameter(conn, utc_now()), stage, run_id),
        )
    else:
        conn.execute(
            f"UPDATE deployment_runs SET current_stage=%s WHERE id=%s{guard}",
            (stage, run_id),
        )


def parse_stage_plan(raw: Any) -> tuple[dict[str, Any], ...]:
    """The flow's pinned stages in order; unreadable JSON yields no stages."""
    try:
        stages = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return ()
    if not isinstance(stages, list):
        return ()
    return tuple(dict(stage) for stage in stages if isinstance(stage, Mapping))


def _uniquely_pinned(
    stages: tuple[dict[str, Any], ...], stage_name: str
) -> dict[str, Any] | None:
    matches = [stage for stage in stages if str(stage.get("name") or "") == stage_name]
    return matches[0] if len(matches) == 1 else None


def is_scoped_qa_stage(stages: tuple[dict[str, Any], ...], stage_name: str) -> bool:
    """Whether the named stage is the flow's scoped-QA stage."""
    stage = _uniquely_pinned(stages, stage_name)
    if stage is None:
        return False
    return (
        stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("step_runner") == QA_STEP_RUNNER
    )


__all__ = [
    "is_scoped_qa_stage",
    "parse_stage_plan",
    "set_current_stage",
]
