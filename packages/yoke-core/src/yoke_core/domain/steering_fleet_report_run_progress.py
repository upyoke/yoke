"""Read each live deployment run's progress row for one steering report.

Every scoped-QA run's members are read as one presented set, so a report's
statement count does not grow with its runs, members or requirements.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report_detectors import parse_stamp

from datetime import datetime
import re

from typing import Any, Optional

from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.deployment_qa_manual_wake import (
    manual_wake_requirements,
)
from yoke_core.domain.deployment_qa_stage_outstanding import (
    member_ref_lookup,
    QaStageOutstanding,
    qa_stage_outstanding,
)
from yoke_core.domain.deployment_qa_stage_wake_state import member_wake_states, stalled_qa_notice
from yoke_core.domain.deployment_run_driver_attachment import (
    is_live,
    parse_attachment,
)
from yoke_core.domain.deployment_run_unpassable_blocking_qa import (
    PinQaDiagnosis,
    diagnose_red_runs,
)
from yoke_core.domain.deployment_run_completion_preview import (
    completion_preview,
)
from yoke_core.domain.schema_read_scope import composition_operation
from yoke_core.domain.deployment_qa_presentation_facts import member_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.steering_fleet_report_deployment_run_facts import (
    LiveRunFactMaps,
    live_deployment_runs,
    load_live_run_facts,
    probe_report_tables,
)
from yoke_core.domain.steering_fleet_report_detectors import age_seconds
from yoke_core.domain.steering_fleet_report_deployment_runs import (
    AnsweredDecision,
    DeploymentRunProgress,
)


def _answered(
    raw: Optional[dict[str, Any]], *, now: datetime
) -> Optional[AnsweredDecision]:
    if raw is None:
        return None
    resolved_at = parse_stamp(raw.get("resolved_at"))
    return AnsweredDecision(
        request_id=int(raw["request_id"]),
        action=str(raw.get("action") or ""),
        resolved_at=resolved_at,
        resolved_seconds=age_seconds(resolved_at, now),
    )


def _stage_lines(
    conn: Any, qa: QaStageOutstanding, wakes: dict[int, str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Run-subject wait lines verbatim; one counted line per waiting member."""
    run_lines: list[str] = []
    member_lines: list[str] = []
    offset = 0
    member_ref = member_ref_lookup(conn, qa.waiting_members)
    for member, count in zip(qa.waiting_members, qa.blocker_counts):
        chunk = qa.lines[offset : offset + count]
        offset += count
        if member is None:
            run_lines.extend(chunk)
            continue
        line = (
            f"member {member_ref(member)}: {count} blocker{'' if count == 1 else 's'}"
        )
        if wake := wakes.get(member):
            line += f" — {wake}"
        details = []
        for reason in chunk:
            ids = re.findall(r"requirement #(\d+)", reason)
            if ids:
                commands = re.findall(r"`(yoke [^`]+)`", reason)
                commands = commands or [f"yoke qa case run --requirement-id {rid}" for rid in ids]
                details.append("requirements " + ", ".join(f"#{rid}" for rid in ids)
                               + ": " + ", ".join(f"`{cmd}`" for cmd in commands))
        member_lines.append(line + ((": " + "; ".join(details)) if details else ""))
    run_lines.extend(qa.lines[offset:])
    return tuple(run_lines), tuple(member_lines)


@composition_operation
def run_progress(
    conn: Any,
    *,
    project_id: int,
    now: datetime,
) -> tuple[DeploymentRunProgress, ...]:
    """Every non-terminal run in the project, with what is holding it.

    Every scoped-QA run's members are presented as one set, so the stage
    walk reads each fact once for all of them rather than per run or member.
    """
    tables = probe_report_tables(conn)
    if not tables.has("deployment_runs"):
        return ()
    live = live_deployment_runs(conn, project_id=project_id)
    if not live:
        return ()
    facts = load_live_run_facts(conn, runs=live, tables=tables)
    slug = resolve_project_slug(conn, project_id)

    @presentation_operation
    @member_presentation
    def rows(connection: Any, subjects: list[tuple[str, int, str]]):
        pins = diagnose_red_runs(
            connection, run_project_id=project_id, red_by_run=facts.red
        )
        return tuple(
            _run_row(
                connection,
                run,
                facts=facts,
                pin_qa=pins.get(str(run["id"]), PinQaDiagnosis()),
                project_id=project_id,
                project_slug=slug,
                now=now,
            )
            for run in live
        )

    return rows(
        conn,
        [
            (run_id, member, stage)
            for run_id, stage in facts.qa_stages.items()
            for member in facts.members.get(run_id, ())
        ],
    )


def _run_row(
    conn: Any,
    run: dict[str, Any],
    *,
    facts: LiveRunFactMaps,
    pin_qa: PinQaDiagnosis,
    project_id: int,
    project_slug: str,
    now: datetime,
) -> DeploymentRunProgress:
    run_id = str(run["id"])
    stage = str(run["current_stage"])
    qa = (
        qa_stage_outstanding(conn, run_id=run_id, stage_name=stage)
        if run_id in facts.qa_stages
        else None
    )
    if qa is None:
        unresolved = facts.unresolved.get(run_id, ())
        outstanding = len(unresolved)
        total_blocking = facts.totals.get(run_id, 0)
    else:
        outstanding = qa.waiting
        total_blocking = qa.subjects
    attached = parse_attachment(run_id, run.get("driver_attachment"))
    driver_phase = (
        attached.phase if attached is not None and is_live(attached, now=now) and run.get("driver_session_live", True) else ""
    )
    waiting = [
        member
        for member in (qa.waiting_members if qa is not None else ())
        if member is not None
    ]
    wakes = (
        member_wake_states(
            conn,
            run_id=run_id,
            stage_name=stage,
            item_ids=waiting,
            project_id=project_id,
            driver_live=bool(driver_phase),
        )
        if waiting
        else {}
    )
    manual = manual_wake_requirements(
        conn,
        run_id=run_id,
        stage_name=stage,
        item_ids=waiting,
        project_slug=project_slug,
    )
    member_lines: tuple[str, ...] = ()
    if qa is not None:
        unresolved, member_lines = _stage_lines(conn, qa, wakes)
    return DeploymentRunProgress(
        run_id=run_id,
        flow=str(run["flow"] or ""),
        status=str(run["status"] or ""),
        stage=stage or "unstarted",
        stage_seconds=age_seconds(facts.entered_at.get(run_id), now),
        outstanding=outstanding,
        total_blocking=total_blocking,
        unresolved=unresolved,
        no_obligation_lines=qa.no_obligation_lines if qa is not None else (),
        red=facts.red.get(run_id, ()),
        answered_decision=_answered(facts.decisions.get(run_id), now=now),
        pin_qa=pin_qa,
        driver_phase=driver_phase,
        member_lines=member_lines,
        completion=completion_preview(conn, run_id, run=run),
        manual_wakes=manual,
        qa_notice_stalled=bool(qa is not None and outstanding and not driver_phase
                              and (stalled_qa_notice(conn, run_id, stage)
                                   or any(state.startswith("not woken:") for state in wakes.values()))),
    )


__all__ = ["run_progress"]
