"""Each run's red blocking QA: the obligations it still owes whose last attempt failed.

One read answers for a whole set of runs. The latest attempt is the canonical
newest actual start, and an obligation a waiver, supersession, replacement,
retraction or triage discharge settled is history rather than red.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_case_failure_kinds import RED_VERDICTS
from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_message_types import row_dict


@dataclass(frozen=True)
class RedRequirement:
    """One unsettled blocking requirement whose latest attempt is red."""

    requirement_id: int
    verdict: str
    item_id: Optional[int]
    project_id: Optional[int]
    member_ref: str

    def describe(self) -> str:
        subject = self.member_ref or "run-wide"
        return f"{subject} #{self.requirement_id} {self.verdict}"


def red_blocking_requirements(
    conn: Any, run_ids: Iterable[str]
) -> dict[str, tuple[RedRequirement, ...]]:
    """Red blocking requirements keyed by run, ordered by requirement id."""
    runs = tuple(dict.fromkeys(str(run_id) for run_id in run_ids))
    if not runs or not (
        _table_exists(conn, "qa_requirements")
        and _table_exists(conn, "qa_runs")
        and _column_exists(conn, "qa_requirements", "deployment_member_item_id")
    ):
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        f"""SELECT r.id, r.deployment_run_id, r.deployment_member_item_id,
                   (SELECT qr.verdict FROM qa_runs qr
                     WHERE qr.id=({latest_execution_id_sql("r.id")})) AS verdict,
                   i.project_id, p.slug, p.public_item_prefix, i.project_sequence
              FROM qa_requirements r
              LEFT JOIN items i ON i.id = r.deployment_member_item_id
              LEFT JOIN projects p ON p.id = i.project_id
             WHERE r.deployment_run_id IN ({", ".join(marker for _ in runs)})
               AND r.blocking_mode = 'blocking'
               AND NOT {settled_obligation_sql(conn, "r")}
             ORDER BY r.deployment_run_id, r.id""",
        runs,
    ).fetchall()
    grouped: dict[str, list[RedRequirement]] = {}
    for raw in rows:
        record = row_dict(raw)
        verdict = str(record["verdict"] or "")
        if verdict not in RED_VERDICTS:
            continue
        item_id = record.get("deployment_member_item_id")
        project_id = record.get("project_id")
        ref = ""
        if record.get("project_sequence") is not None:
            ref = format_item_ref(
                record["slug"], record["public_item_prefix"], record["project_sequence"]
            )
        grouped.setdefault(str(record["deployment_run_id"]), []).append(
            RedRequirement(
                requirement_id=int(record["id"]),
                verdict=verdict,
                item_id=int(item_id) if item_id is not None else None,
                project_id=int(project_id) if project_id is not None else None,
                member_ref=ref,
            )
        )
    return {run_id: tuple(found) for run_id, found in grouped.items()}


__all__ = ["RedRequirement", "red_blocking_requirements"]
