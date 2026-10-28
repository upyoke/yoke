"""Read which QA-stage subjects a drive would still wait on.

A run sitting at a scoped QA stage is not waiting on unsettled
``qa_requirements`` rows. The driver asks
:func:`materialize_and_gate_deployment_qa_stage`, which waits on
:class:`QaCasesNotSelectedError` or on
:func:`deployment_qa_stage_status`. This module is that walk without
materializing, settling, or waking anyone, so a report and a drive cannot
disagree about whether anything is outstanding.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from yoke_core.domain.item_ref_render import ItemRefLookup, render_item_ref_lookup
from yoke_core.domain.deployment_run_membership_removals import removed_item_ids
from yoke_core.domain import deployment_run_item_qa_membership as item_qa

from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA
from yoke_core.domain.deployment_qa_frozen_plan_selection import (
    frozen_stage_plans,
    member_requirements,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_NOT_RUN,
    stage_acceptance,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_stage_gate import ACCEPTANCE_QA_KIND
from yoke_core.domain.deployment_qa_stage_named_cases import stage_names_cases
from yoke_core.domain.post_deploy_verification_answer import (
    cases_not_selected_refusal,
    NOT_REQUIRED,
    member_post_deploy_answer,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.deployment_qa_presentation_facts import (
    member_presentation,
    presented_member_ids,
    run_facts,
    run_member_rows,
    subject_requirement_rows,
)
from yoke_core.domain.deployment_qa_presentation_reads import (
    presentation_operation,
    presentation_read,
)
from yoke_core.domain.steering_fleet_report_detectors import marker


_FIRST_WAITING = ContextVar("qa_first_waiting", default=False)


def first_waiting_qa_stage(conn, *, run_id, stage_name):
    """Ask the canonical stage reader only for the first real blocker."""
    token = _FIRST_WAITING.set(True)
    try:
        return qa_stage_outstanding(conn, run_id=run_id, stage_name=stage_name)
    finally:
        _FIRST_WAITING.reset(token)


@dataclass(frozen=True)
class QaStageOutstanding:
    """One current QA stage's subjects, and the wait lines a drive would print.

    ``waiting_members`` names each subject still owed QA: a member item id on
    an item-scoped stage, ``None`` for the run itself on a run-scoped one.
    ``blocker_counts`` is parallel to it: how many wait lines each subject
    contributed, so a report can show one counted line per member instead
    of every line. ``member_states`` is parallel too: each waiting subject's
    acceptance state, which tells a wake whether running cases can help.
    """

    lines: tuple[str, ...]
    subjects: int
    waiting: int
    waiting_members: tuple[int | None, ...] = ()
    no_obligation_lines: tuple[str, ...] = ()
    blocker_counts: tuple[int, ...] = ()
    member_states: tuple[str, ...] = ()

    def member_blockers(self) -> dict[int | None, tuple[str, tuple[str, ...]]]:
        """Each waiting subject's acceptance state and its own wait lines."""
        found: dict[int | None, tuple[str, tuple[str, ...]]] = {}
        start = 0
        for member, count, state in zip(
            self.waiting_members, self.blocker_counts, self.member_states
        ):
            found[member] = (state, self.lines[start : start + count])
            start += count
        return found


@presentation_operation
def qa_stage_outstanding(
    conn: Any, *, run_id: str, stage_name: str, stop_at_first_waiting: bool = False
) -> Optional[QaStageOutstanding]:
    """Outstanding waits for *stage_name* when that stage is scoped QA.

    ``None`` means the report should keep the completion-boundary readers:
    this is not a QA stage, or the frozen subject cannot be evaluated.
    ``stop_at_first_waiting`` answers only whether anything is waiting: the
    walk ends at the first waiting subject, so ``waiting`` and the lines
    cover only the subjects evaluated up to it. Run-wide facts such as the candidate's
    pinned release are read once per evaluation and shared by every member.
    """
    stage = _qa_stage(conn, run_id=run_id, stage_name=stage_name)
    if stage is None:
        return None
    try:
        return _evaluate(
            conn,
            run_id=run_id,
            stage=stage,
            stop_at_first_waiting=stop_at_first_waiting or _FIRST_WAITING.get(),
        )
    except (LookupError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _qa_stage(conn: Any, *, run_id: str, stage_name: str) -> Optional[dict[str, Any]]:
    if not (
        _table_exists(conn, "deployment_runs")
        and _table_exists(conn, "deployment_flows")
    ):
        return None
    row = run_facts(conn, run_id)
    if row is None:
        row = conn.execute(
            f"""SELECT df.stages FROM deployment_runs dr
                  JOIN deployment_flows df ON df.id = dr.flow
                 WHERE dr.id = {marker(conn)}""",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    raw = row["stages"] if hasattr(row, "keys") else row[0]
    try:
        stages = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return None
    if not isinstance(stages, list):
        return None
    matches = [
        dict(stage)
        for stage in stages
        if isinstance(stage, Mapping) and str(stage.get("name") or "") == stage_name
    ]
    if len(matches) != 1:
        return None
    stage = matches[0]
    if (
        stage.get("stage_kind") != STAGE_KIND_QA
        or stage.get("step_runner") != QA_STEP_RUNNER
    ):
        return None
    return stage


def _subjects(conn: Any, run_id: str, stage: Mapping[str, Any]) -> list[int | None]:
    if stage.get("scope") == "item":
        presented = run_member_rows(conn, run_id)
        if presented is not None:
            return sorted(presented)
        rows = conn.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
            (run_id,),
        ).fetchall()
        return [int(row["item_id"] if hasattr(row, "keys") else row[0]) for row in rows]
    return [None]


def _has_method_id(
    conn: Any, *, run_id: str, stage_name: str, member: int | None
) -> bool:
    if not _table_exists(conn, "qa_requirements"):
        return False
    rows = subject_requirement_rows(conn, run_id, stage_name, member)
    if rows is not None:
        return any(row["method_id"] is not None for row in rows)
    row = conn.execute(
        "SELECT 1 FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s "
        "AND method_id IS NOT NULL LIMIT 1",
        (run_id, stage_name, member or 0),
    ).fetchone()
    return row is not None


def _unselected_reason(
    conn: Any, subject: Mapping[str, Any], *, target: Mapping[str, Any]
) -> str | None:
    admitted = member_requirements(conn, subject, target=target)
    frozen = frozen_stage_plans(conn, subject, target=target, admitted=admitted)
    if stage_names_cases(conn, subject, frozen_plans=frozen, admitted=admitted):
        return None
    if member_post_deploy_answer(conn, subject).discharges_without_cases:
        return None
    return cases_not_selected_refusal()


def _member_lines(
    conn: Any, *, run_id: str, stage: Mapping[str, Any], member: int | None, label: str
) -> tuple[list[str], list[str], str]:
    """Driver-shaped wait lines, exemption notes and acceptance state."""
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=str(stage["name"]),
        member_item_id=member,
        require_active=False,
    )
    member_answer = member_post_deploy_answer(conn, subject)
    if member_answer.verdict == NOT_REQUIRED:
        return [], [f"{label}: {reason}" for reason in member_answer.reasons], ""
    target = deployment_qa_execution_target(conn, subject)
    if not _has_method_id(
        conn, run_id=run_id, stage_name=str(stage["name"]), member=member
    ):
        unselected = _unselected_reason(conn, subject, target=target)
        if unselected:
            return [f"{label}: {unselected}"], [], STAGE_NOT_RUN
    acceptance = stage_acceptance(
        conn,
        subject=subject,
        target=target,
        acceptance_qa_kind=ACCEPTANCE_QA_KIND,
    )
    if acceptance.accepted:
        return [], [], acceptance.state
    if acceptance.state == STAGE_NOT_RUN and member_answer.discharges_without_cases:
        return [], [], acceptance.state
    lines = [f"{label}: {reason}" for reason in acceptance.blockers]
    return lines, [], acceptance.state


def member_ref_lookup(conn: Any, members: Iterable[int | None]) -> ItemRefLookup:
    """Public refs of these members; inside a presentation, of every presented one."""
    wanted = {int(member) for member in members if member}
    presented = presented_member_ids(conn)
    ids = tuple(presented) if presented and wanted <= set(presented) else tuple(wanted)
    return presentation_read(
        conn, ("qa_member_refs", ids), lambda: render_item_ref_lookup(conn, ids)
    )


def _evaluate(
    conn: Any, *, run_id: str, stage: Mapping[str, Any], stop_at_first_waiting: bool
) -> QaStageOutstanding:
    members = _subjects(conn, run_id, stage)
    if (
        stage.get("scope") == "item"
        and not members
        and not removed_item_ids(conn, run_id)
    ):
        # Asked again here, failing closed, rather than trusting pre-start.
        if refusal := item_qa.memberless_item_qa_refusal(conn, run_id):
            return QaStageOutstanding(lines=(refusal,), subjects=1, waiting=1)
        return QaStageOutstanding(
            lines=(),
            subjects=0,
            waiting=0,
            no_obligation_lines=(item_qa.NO_MEMBER_OWES_TARGET,),
        )
    member_ref = member_ref_lookup(conn, members)

    # Every member's facts are read as one set for the walk, not per member.
    @member_presentation
    def walk(connection, subjects):
        found: list[tuple[int | None, list[str], list[str], str]] = []
        for member in members:
            label = f"member {member_ref(member)}" if member is not None else "run"
            member_lines, notes, state = _member_lines(
                connection, run_id=run_id, stage=stage, member=member, label=label
            )
            found.append((member, member_lines, notes, state))
            if member_lines and stop_at_first_waiting:
                break
        return found

    stage_name = str(stage["name"])
    lines: list[str] = []
    waiting_members: list[int | None] = []
    blocker_counts: list[int] = []
    member_states: list[str] = []
    no_obligation_lines: list[str] = []
    subjects = [(run_id, member, stage_name) for member in members if member]
    for member, member_lines, notes, state in walk(conn, subjects):
        no_obligation_lines.extend(notes)
        if member_lines:
            waiting_members.append(member)
            blocker_counts.append(len(member_lines))
            member_states.append(state)
            lines.extend(member_lines)
    if stage.get("scope") == "item" and not (stop_at_first_waiting and lines):
        from yoke_core.domain.deployment_qa_plan_group_writes import group_blockers

        for label, state, blockers in group_blockers(conn, run_id, stage_name):
            waiting_members.append(None)  # a plan group: memberless
            blocker_counts.append(len(blockers))
            member_states.append(state)
            lines.extend(f"{label}: {reason}" for reason in blockers)
    return QaStageOutstanding(
        lines=tuple(lines),
        subjects=len(members),
        waiting=len(waiting_members),
        waiting_members=tuple(waiting_members),
        no_obligation_lines=tuple(no_obligation_lines),
        blocker_counts=tuple(blocker_counts),
        member_states=tuple(member_states),
    )


__all__ = ["QaStageOutstanding", "member_ref_lookup", "qa_stage_outstanding"]
