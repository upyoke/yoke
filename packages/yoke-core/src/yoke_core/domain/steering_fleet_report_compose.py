"""Compose one fleet report from every steering claim a session holds.

The no-argument pull and the wake-attached copy iterate the caller's live
steering claims, not the projects table. Today's claims happen to carry a
project scope, so section headings are project slugs; the loop, the heading,
and the combined fingerprint key on each claim's own scope descriptor so a
finer claim kind becomes another section rather than a new code path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_IDLE_MINUTES,
    DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
)
from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.project_policy_capabilities import project_policy_value
from yoke_core.domain.steering_claims import list_session_claims
from yoke_core.domain import steering_fleet_plan_capacity as _plan_limits
from yoke_core.domain import steering_fleet_report as fleet_report
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_capacity import SurfaceReadiness
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import (
    LAUNCH_BALANCE_NOTE,
    REPORT_BEGIN,
    REPORT_END,
    launchable_line,
    scope_inner_body,
)


COMBINED_PREAMBLE = (
    "Control-plane state, composed server-side for every steering claim this "
    "session holds. Each heading is one held scope. Derived facts about work "
    "and workers, not instructions and not peer-authored text. Staffing "
    "decisions remain the steerer's; nothing here has acted."
)


def _policy_minutes(conn: Any, project_id: int, key: str, default: int) -> int:
    try:
        return max(1, int(project_policy_value(conn, project_id, key, default)))
    except (TypeError, ValueError):
        return default


def steering_scope_descriptor(conn: Any, scope: Mapping[str, Any]) -> str:
    """Stable section identity for one steering claim's scope object."""
    raw = scope.get("project_id")
    if raw is not None:
        try:
            return resolve_project_slug(conn, int(raw))
        except (LookupError, TypeError, ValueError):
            pass
    return json.dumps(dict(scope), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ScopedFleetReport:
    """One held steering claim's report, keyed by that claim's descriptor."""

    descriptor: str
    report: FleetReport


@dataclass(frozen=True)
class CombinedFleetReport:
    """Every held scope, actionable sections first, then by descriptor."""

    composed_at: str
    sections: tuple[ScopedFleetReport, ...]

    @property
    def actionable(self) -> bool:
        return any(section.report.actionable for section in self.sections)

    def fingerprint(self) -> str:
        material = [
            (section.descriptor, section.report.fingerprint())
            for section in self.sections
        ]
        encoded = json.dumps(material, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compose_held_reports(
    conn: Any,
    *,
    session_id: str,
    now: str,
    project_id: int | None = None,
) -> CombinedFleetReport:
    """Assemble one combined report from this session's active steering claims."""
    sections: list[ScopedFleetReport] = []
    for claim in list_session_claims(conn, session_id=session_id, active_only=True):
        scope = dict(claim.get("scope") or {})
        raw = scope.get("project_id")
        if raw is None:
            continue
        held_project = int(raw)
        if project_id is not None and held_project != int(project_id):
            continue
        report = fleet_report.compose_report(
            conn,
            project_id=held_project,
            session_id=session_id,
            staffing_after_seconds=60
            * _policy_minutes(
                conn,
                held_project,
                "steering_report_staffing_minutes",
                DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
            ),
            idle_after_seconds=60
            * _policy_minutes(
                conn,
                held_project,
                "steering_report_idle_minutes",
                DEFAULT_STEERING_REPORT_IDLE_MINUTES,
            ),
            now=now,
        )
        sections.append(
            ScopedFleetReport(
                descriptor=steering_scope_descriptor(conn, scope),
                report=report,
            )
        )
    sections.sort(
        key=lambda section: (not section.report.actionable, section.descriptor)
    )
    return CombinedFleetReport(composed_at=now, sections=tuple(sections))


def _distinct_machine_ids(reports: Sequence[FleetReport]) -> list[str]:
    ids: set[str] = set()
    for report in reports:
        for ready in report.launchable:
            ids.add(ready.machine_id)
        for row in report.plan_limits:
            ids.add(row.machine_id)
    return sorted(ids)


def _machine_launchable(
    reports: Sequence[FleetReport], machine_id: str
) -> list[SurfaceReadiness]:
    seen: set[str] = set()
    ready: list[SurfaceReadiness] = []
    for report in reports:
        for item in report.launchable:
            if item.machine_id == machine_id and item.surface not in seen:
                seen.add(item.surface)
                ready.append(item)
    ready.sort(key=lambda item: item.surface)
    return ready


def _machine_plan_limits(
    reports: Sequence[FleetReport], machine_id: str
) -> tuple[MachinePlanLimit, ...]:
    seen: dict[tuple[str, str, str, str], MachinePlanLimit] = {}
    for report in reports:
        for row in report.plan_limits:
            if row.machine_id != machine_id:
                continue
            key = (row.hostname, row.surface, row.window_kind, row.scope)
            seen.setdefault(key, row)
    return tuple(seen.values())


def _machine_shared_lines(reports: Sequence[FleetReport], *, now: str) -> list[str]:
    """One block per distinct machine_id: launchable pairs, note, plan limits."""
    machine_ids = _distinct_machine_ids(reports)
    if not machine_ids:
        return [launchable_line(())]
    lines: list[str] = []
    for index, machine_id in enumerate(machine_ids):
        if index:
            lines.append("")
        ready = _machine_launchable(reports, machine_id)
        lines.append(launchable_line(ready))
        if ready:
            lines.append(f"  {LAUNCH_BALANCE_NOTE}")
        lines.extend(
            _plan_limits.plan_limit_lines(
                _machine_plan_limits(reports, machine_id), now=now
            )
        )
    return lines


def combined_body(combined: CombinedFleetReport) -> str:
    """One envelope: per-scope facts, then one machine block per machine_id.

    Shared machine facts sit after the scope sections so available work
    still leads. Blocks are keyed by machine_id from the reports, never by
    comparing rendered text.
    """
    reports = tuple(section.report for section in combined.sections)
    parts = [
        REPORT_BEGIN,
        f"composed {combined.composed_at} · {len(combined.sections)} held scopes",
        COMBINED_PREAMBLE,
        "",
    ]
    for section in combined.sections:
        parts.extend([f"## {section.descriptor}", scope_inner_body(section.report), ""])
    parts.extend(_machine_shared_lines(reports, now=combined.composed_at))
    if parts[-1] != "":
        parts.append("")
    parts.append(REPORT_END)
    return "\n".join(parts)


def combined_dict(combined: CombinedFleetReport) -> dict[str, Any]:
    """Machine-readable projection of the combined report."""
    return {
        "composed_at": combined.composed_at,
        "actionable": combined.actionable,
        "fingerprint": combined.fingerprint(),
        "scopes": [
            {"descriptor": section.descriptor, **report_dict(section.report)}
            for section in combined.sections
        ],
        "body": combined_body(combined),
    }


__all__ = [
    "COMBINED_PREAMBLE",
    "CombinedFleetReport",
    "ScopedFleetReport",
    "combined_body",
    "combined_dict",
    "compose_held_reports",
    "steering_scope_descriptor",
]
