"""Item QA that steering starts, not the stage it belongs to.

A requirement with ``wake_path: "manual"`` (see
:mod:`yoke_contracts.qa_case_wake_path`) can only be judged once real
production traffic exists. Its stage still waits on it, but the stage driver
does not wake the member's owner while one is open: one stage execution runs
the member's whole roster, so waking early would run the manual case before
its evidence exists. Steering reads these rows in the fleet report, checks the
named evidence with registered reads, and wakes the owner with the command
each row carries.

A manual requirement is open until something records a run against it, or it
is waived, superseded or retracted. Nothing here schedules, polls or times
out; the report states the wait and a person decides.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from yoke_contracts.qa_case_wake_path import MANUAL
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.session_staleness import activity_liveness
from yoke_core.domain.work_claim_targets import scope_int_sql

#: What the owner column says when no live session holds the item.
NO_OWNER = "no live claim holder; staff the item before waking it"


@dataclass(frozen=True)
class ManualWakeRequirement:
    """One open manual-wake requirement and who would run it."""

    run_id: str
    stage: str
    item_id: int
    item_ref: str
    project_slug: str
    requirement_id: int
    case_key: str
    wake_evidence: str
    owner_session_id: str = ""
    owner_state: str = ""

    def run_command(self) -> str:
        """The member's stage run, exactly as an automatic stage wake names it."""
        return (
            f"yoke qa plan run --deployment-run-id {self.run_id} --stage "
            f"{self.stage} --member {self.item_ref} --project {self.project_slug}"
        )

    def wake_command(self) -> str:
        """The message steering sends to wake the owner, through ``yoke say``."""
        body = (
            f"Manual-wake QA for {self.item_ref} is ready: deployment run "
            f"{self.run_id}, stage {self.stage!r}, requirement "
            f"#{self.requirement_id} (case {self.case_key}). Steering confirmed "
            f"its evidence exists: {self.wake_evidence} Run the member's cases "
            f"now: '{self.run_command()}'. Check 'yoke deployment-runs get "
            f"{self.run_id}' for the current state."
        )
        return (
            f"printf %s {shlex.quote(body)} | yoke say --stdin --item {self.item_ref}"
        )

    def owner(self) -> str:
        if not self.owner_session_id:
            return NO_OWNER
        return f"session {self.owner_session_id} ({self.owner_state})"


def _open_rows(
    conn: Any, *, run_id: str, stage_name: str, item_ids: list[int]
) -> list[Any]:
    p = marker(conn)
    return conn.execute(
        "SELECT q.id, q.deployment_member_item_id, COALESCE(q.plan_case_key,''), "
        "COALESCE(q.wake_evidence,'') FROM qa_requirements q "
        f"WHERE q.deployment_run_id={p} AND q.deployment_stage={p} "
        f"AND q.wake_path={p} AND q.method_id IS NOT NULL "
        "AND q.waived_at IS NULL AND q.superseded_at IS NULL "
        "AND q.retracted_at IS NULL "
        f"AND q.deployment_member_item_id IN ({','.join([p] * len(item_ids))}) "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs r WHERE r.qa_requirement_id=q.id) "
        "ORDER BY q.deployment_member_item_id, q.id",
        (run_id, stage_name, MANUAL, *item_ids),
    ).fetchall()


def member_holds_for_manual_wake(
    conn: Any, *, run_id: str, stage_name: str, member_item_id: int
) -> bool:
    """Whether the stage driver must leave this member's owner unwoken."""
    return bool(
        _open_rows(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            item_ids=[int(member_item_id)],
        )
    )


def _owner(conn: Any, item_id: int) -> tuple[str, str]:
    p = marker(conn)
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    row = conn.execute(
        "SELECT hs.session_id, hs.ended_at, hs.terminated_at, hs.last_heartbeat, "
        "hs.last_tool_call_at, COALESCE(hs.mode,'') FROM work_claims wc "
        "JOIN harness_sessions hs ON hs.session_id=wc.session_id "
        "WHERE wc.released_at IS NULL AND hs.terminated_at IS NULL "
        f"AND wc.target_kind='item' AND {item_scope}={p} "
        "ORDER BY CASE WHEN hs.ended_at IS NULL THEN 0 ELSE 1 END, wc.id DESC "
        "LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return "", ""
    keys = ("ended_at", "terminated_at", "last_heartbeat", "last_tool_call_at")
    liveness = activity_liveness(dict(zip(keys, tuple(row)[1:5])))
    mode = str(tuple(row)[5] or "")
    return str(tuple(row)[0]), f"{liveness}, mode {mode}" if mode else liveness


def manual_wake_requirements(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    item_ids: Iterable[int],
    project_slug: str,
) -> tuple[ManualWakeRequirement, ...]:
    """Every open manual-wake requirement of these waiting members."""
    from yoke_core.domain.project_identity import render_item_ref

    members = sorted({int(item_id) for item_id in item_ids})
    if not members:
        return ()
    rows = _open_rows(conn, run_id=run_id, stage_name=stage_name, item_ids=members)
    owners: dict[int, tuple[str, str]] = {}
    entries = []
    for row in rows:
        requirement_id, member, case_key, evidence = tuple(row)
        member = int(member)
        if member not in owners:
            owners[member] = _owner(conn, member)
        session_id, state = owners[member]
        entries.append(
            ManualWakeRequirement(
                run_id=run_id,
                stage=stage_name,
                item_id=member,
                item_ref=render_item_ref(conn, member),
                project_slug=project_slug,
                requirement_id=int(requirement_id),
                case_key=str(case_key),
                wake_evidence=str(evidence),
                owner_session_id=session_id,
                owner_state=state,
            )
        )
    return tuple(entries)


__all__ = [
    "ManualWakeRequirement",
    "NO_OWNER",
    "manual_wake_requirements",
    "member_holds_for_manual_wake",
]
