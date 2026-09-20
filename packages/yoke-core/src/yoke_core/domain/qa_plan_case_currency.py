"""Whether a materialized QA requirement still matches the plan case behind it.

Materialization copies a plan case onto ``qa_requirements`` and nothing read
that link in the edit direction, so a corrected plan reached the plan alone.
The row kept the body it was materialized with, a deployment run later froze
an admitted copy of that row, and the walker failed on the very defect the
correction had removed — nine hours after the edit read back correct.

The comparison cannot be a field digest, because the two shapes do not line
up: one ``success_policy`` document against a case's id plus params, one row
per host baseline against the case's array, and ``method_name`` /
``runner_id`` / ``verdict_path`` / ``capability_requirements`` that exist on no
plan case at all. So this re-runs the materialization transform
(:mod:`qa_plan_case_definition`) to derive what the row SHOULD be, and diffs
that against what it IS. Same derivation the writers use, so a row can only be
reported stale when a refresh would genuinely change it.

Four answers, never a silent fifth: ``current``, ``stale`` with the fields that
moved, ``orphaned`` when the plan no longer carries the case, and
``unreadable`` when the plan case can no longer be derived at all. Each
non-current answer carries the command that actually reaches that row, chosen
from the row's own subject columns rather than from one remembered recipe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_plan_case_definition import (
    case_baselines,
    materialized_definition,
    plan_cases,
)
from yoke_core.domain.qa_plan_execution_store import canonical, marker
from yoke_core.domain.qa_plan_refresh_safety import refresh_recovery
from yoke_core.domain.qa_plan_management import QaPlanError, _plan_row

#: The executable columns a refresh would rewrite from the plan. Everything
#: materialization decides for itself is excluded on purpose: ``qa_phase``
#: comes from the attachment, the execution target from environment
#: resolution, and ``plan_id`` / ``plan_case_key`` / ``host_baseline`` are the
#: link itself rather than content that can drift.
PLAN_DEFINITION_COLUMNS: tuple[str, ...] = (
    "method_id",
    "method_name",
    "runner_id",
    "verdict_path",
    "instructions",
    "expected_outcome",
    "method_config",
    "entry_surface",
    "required_completion",
    "success_policy",
    "capability_requirements",
    "case_position",
    "baseline_position",
)

STALE_PLAN_CASE_CODE = "plan_case_superseded"

CURRENT = "current"
STALE = "stale"
ORPHANED = "orphaned"
UNREADABLE = "unreadable"

#: Columns identifying which subject a row was materialized for, which is what
#: decides the refresh command that can reach it.
_SUBJECT_COLUMNS = (
    "item_id",
    "deployment_run_id",
    "deployment_stage",
    "deployment_member_item_id",
    "plan_id",
    "plan_case_key",
    "host_baseline",
    "qa_phase",
    "workflow_transition_id",
    "waived_at",
)


class PlanCaseCurrencyError(ValueError):
    """A materialized row no longer matches its plan; the message names why."""


@dataclass(frozen=True)
class PlanCaseDivergence:
    """One materialized row that is no longer what its plan case says."""

    requirement_id: int
    plan_id: int
    case_key: str
    host_baseline: Optional[str]
    state: str
    fields: tuple[str, ...] = ()
    detail: str = ""
    refresh_command: str = ""

    def message(self) -> str:
        """The named finding, with the command that reaches this exact row."""
        if self.state == STALE:
            what = (
                f"its plan case {self.case_key!r} has since been amended "
                f"({', '.join(self.fields)})"
            )
        elif self.state == ORPHANED:
            what = (
                f"plan {self.plan_id} no longer carries case {self.case_key!r} "
                f"at baseline {self.host_baseline!r}"
            )
        else:
            what = (
                f"plan case {self.case_key!r} can no longer be materialized: "
                f"{self.detail}"
            )
        return (
            f"{STALE_PLAN_CASE_CODE}: QA requirement {self.requirement_id} was "
            f"materialized from QA plan {self.plan_id}, and {what}. Running it "
            "would judge against a definition the plan has already replaced. "
            f"{self.refresh_command}"
        )


def _comparable(value: Any) -> str:
    """One stable string per stored value, across both sides' storage shapes.

    A column stored as JSON text on the row and produced as text by the
    derivation still has to survive a backend that hands back a decoded
    object, so both sides are canonicalised rather than compared raw.
    """
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
        return canonical(parsed)
    if isinstance(value, (int, float, bool)):
        return str(value)
    return canonical(value)


def _row(conn: Any, requirement_id: int) -> Any:
    columns = ",".join((*_SUBJECT_COLUMNS, *PLAN_DEFINITION_COLUMNS))
    return query_one(
        conn,
        f"SELECT id,{columns} FROM qa_requirements WHERE id={marker(conn)}",
        (int(requirement_id),),
    )


def _divergence_for_row(conn: Any, row: Any) -> Optional[PlanCaseDivergence]:
    """Compare one materialized row against its plan case, or return ``None``."""
    if row["plan_id"] is None:
        return None
    plan_id = int(row["plan_id"])
    case_key = str(row["plan_case_key"] or "")
    baseline = row["host_baseline"]
    common = {
        "requirement_id": int(row["id"]),
        "plan_id": plan_id,
        "case_key": case_key,
        "host_baseline": baseline,
        "refresh_command": refresh_recovery(conn, row),
    }
    try:
        plan = _plan_row(conn, plan_id)
        cases = {str(case["case_key"]): case for case in plan_cases(conn, plan_id)}
    except QaPlanError as exc:
        return PlanCaseDivergence(state=UNREADABLE, detail=str(exc), **common)
    case = cases.get(case_key)
    if case is None:
        return PlanCaseDivergence(state=ORPHANED, **common)
    baselines = case_baselines(case)
    if baseline not in baselines:
        return PlanCaseDivergence(state=ORPHANED, **common)
    try:
        definition = materialized_definition(
            plan=plan,
            case=case,
            qa_phase=str(row["qa_phase"] or ""),
            baseline=baseline,
            baseline_position=baselines.index(baseline) + 1,
            transition_id=row["workflow_transition_id"],
        )
    except (QaPlanError, ValueError) as exc:
        return PlanCaseDivergence(state=UNREADABLE, detail=str(exc), **common)
    fields = tuple(
        column
        for column in PLAN_DEFINITION_COLUMNS
        if _comparable(row[column]) != _comparable(definition[column])
    )
    if not fields:
        return None
    return PlanCaseDivergence(state=STALE, fields=fields, **common)


def plan_case_divergence(
    conn: Any, requirement_id: int
) -> Optional[PlanCaseDivergence]:
    """How this row differs from its plan case, or ``None`` when it does not.

    ``None`` also covers every row that cannot be behind a plan: one never
    materialized from a plan, and an admitted deployment-stage copy, whose own
    currency belongs to :mod:`qa_admitted_case_currency` one link further down.
    """
    row = _row(conn, int(requirement_id))
    if row is None:
        return None
    return _divergence_for_row(conn, row)


def rows_behind_plan(conn: Any, plan_id: int) -> list[PlanCaseDivergence]:
    """Every live row materialized from this plan that no longer matches it.

    Waived rows are left out: a waived row runs nothing, so it cannot certify
    against a superseded body, and naming it would bury the rows that can.
    """
    columns = ",".join((*_SUBJECT_COLUMNS, *PLAN_DEFINITION_COLUMNS))
    rows = query_rows(
        conn,
        f"SELECT id,{columns} FROM qa_requirements "
        f"WHERE plan_id={marker(conn)} AND waived_at IS NULL ORDER BY id",
        (int(plan_id),),
    )
    found = (_divergence_for_row(conn, row) for row in rows)
    return [divergence for divergence in found if divergence is not None]


def plan_drift_report(conn: Any, plan_id: int) -> dict[str, Any]:
    """What an edit to this plan left behind, for the edit's own result.

    An author who corrects a case learns in the same breath which rows are now
    behind it, so a correction can never be silently partial again.
    """
    divergences = rows_behind_plan(conn, int(plan_id))
    return {
        "requirements_behind_plan": [
            {
                "requirement_id": divergence.requirement_id,
                "case_key": divergence.case_key,
                "host_baseline": divergence.host_baseline,
                "state": divergence.state,
                "diverging_fields": list(divergence.fields),
                "recovery": divergence.message(),
            }
            for divergence in divergences
        ],
        "requirements_behind_plan_count": len(divergences),
    }


def annotate_plan_currency(
    conn: Any, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mark every materialized row in *rows* current or behind its plan case.

    This is what makes drift readable without opening two bodies side by side:
    a reader listing requirements is told which definition each row will judge
    against, and which fields moved when that is no longer the plan's own.
    """
    for row in rows:
        if row.get("plan_id") in (None, ""):
            continue
        divergence = plan_case_divergence(conn, int(row["id"]))
        row["plan_currency"] = CURRENT if divergence is None else divergence.state
        row["plan_diverging_fields"] = (
            list(divergence.fields) if divergence is not None else []
        )
    return rows


def annotate_requirement_currency(
    conn: Any, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mark each row against every copy edge above it, in chain order.

    A requirement row can be a copy twice over: materialized from a plan case,
    and then admitted onto a deployment stage as a further copy of itself. A
    reader asking "will this row judge against what its author means today?"
    needs both answers, and asking two readers separately is how the two
    edges drift apart in what they report.
    """
    from yoke_core.domain.qa_admitted_case_currency import (
        annotate_admitted_currency,
    )

    return annotate_plan_currency(conn, annotate_admitted_currency(conn, rows))


def require_current_plan_case(conn: Any, requirement_id: int) -> None:
    """Raise the named refusal when this row's plan case has moved under it."""
    divergence = plan_case_divergence(conn, int(requirement_id))
    if divergence is not None:
        raise PlanCaseCurrencyError(divergence.message())


__all__ = [
    "CURRENT",
    "ORPHANED",
    "PLAN_DEFINITION_COLUMNS",
    "PlanCaseCurrencyError",
    "PlanCaseDivergence",
    "STALE",
    "STALE_PLAN_CASE_CODE",
    "UNREADABLE",
    "annotate_plan_currency",
    "annotate_requirement_currency",
    "plan_case_divergence",
    "plan_drift_report",
    "require_current_plan_case",
    "rows_behind_plan",
]
