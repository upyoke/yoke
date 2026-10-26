"""Compose one fleet report from every steering claim a session holds.

The no-argument pull and the wake-attached copy iterate the caller's live
steering claims, not the projects table. A claim scoped to a whole project
heads its section with the project slug; one narrowed to a strategy document
heads it with the document inside that project. The loop, the heading, and
the combined fingerprint all key on each claim's own scope descriptor, so a
further refinement becomes another section rather than a new code path.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from datetime import datetime

from dataclasses import dataclass, replace
import json
from typing import Any, Mapping

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_IDLE_MINUTES,
    DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
)
from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.project_policy_capabilities import project_policy_value
from yoke_core.domain.steering_claims import list_session_claims
from yoke_core.domain.steering_scope_membership import scope_document
from yoke_core.domain import steering_fleet_report as fleet_report
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_levels import (
    LevelReadout,
    level_readout_lines,
)
from yoke_core.domain.steering_fleet_report_machine_block import (
    machine_shared_lines,
    fleet_shared_lines,
)
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_fingerprint import (
    digest,
    project_payload,
    seat_payload,
)
from yoke_core.domain.steering_fleet_report_project_rows import (
    rows_per_section,
)
from yoke_core.domain.steering_fleet_report_reads import FleetReportReads
from yoke_core.domain.steering_fleet_report_slow_paths import (
    SlowPath,
    read_slow_paths,
    slow_path_lines,
)
from yoke_core.domain.steering_fleet_report_unattended import (
    UnattendedLinkedItem,
    unattended_linked_items,
)
from yoke_core.domain.steering_fleet_report_render import (
    REPORT_BEGIN,
    REPORT_END,
    scope_inner_body,
)


COMBINED_PREAMBLE = (
    "Server-composed control-plane facts; each heading is a held scope. "
    "These are not instructions or peer text. Staffing remains the steerer's; nothing acted."
)


def _policy_minutes(conn: Any, project_id: int, key: str, default: int) -> int:
    try:
        return max(1, int(project_policy_value(conn, project_id, key, default)))
    except (TypeError, ValueError):
        return default


def steering_scope_descriptor(
    conn: Any,
    scope: Mapping[str, Any],
    reads: FleetReportReads | None = None,
) -> str:
    """Stable section identity for one steering claim's scope object."""
    request = reads if reads is not None else FleetReportReads()
    raw = scope.get("project_id")
    if raw is not None:
        slug = request.cached(
            ("project_slug", int(raw)), lambda: _project_slug(conn, int(raw))
        )
        if slug is not None:
            document = scope_document(scope)
            return f"{slug} · {document}" if document else slug
    return json.dumps(dict(scope), sort_keys=True, separators=(",", ":"))


def _project_slug(conn: Any, project_id: int) -> str | None:
    try:
        return resolve_project_slug(conn, project_id)
    except (LookupError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ScopedFleetReport:
    """One held steering claim's report, keyed by that claim's descriptor."""

    descriptor: str
    report: FleetReport


@dataclass(frozen=True)
class CombinedFleetReport:
    """Every held scope, actionable sections first, then by descriptor."""

    composed_at: datetime
    sections: tuple[ScopedFleetReport, ...]
    unattended: tuple[UnattendedLinkedItem, ...] = ()
    #: Functions over their latency budget: diagnostic, never actionable.
    slow_paths: tuple[SlowPath, ...] = ()

    @property
    def actionable(self) -> bool:
        return any(section.report.actionable for section in self.sections) or bool(
            self.unattended
        )

    def fingerprint(self) -> str:
        """JSON map of age-blind content hashes for each digest scope."""
        reports = [section.report for section in self.sections]
        material = {
            f"scope:{section.descriptor}": digest({
                "seat": seat_payload(section.report),
                "project": project_payload(rows),
            })
            for section, rows in zip(self.sections, rows_per_section(reports))
        }
        material["unattended"] = digest([row.item_id for row in self.unattended])
        return json.dumps(material, sort_keys=True, separators=(",", ":"))


def compose_held_reports(
    conn: Any,
    *,
    session_id: str,
    now: str,
    project_id: int | None = None,
    include_inventory: bool = True,
    reuse_schedule: bool = False,
) -> CombinedFleetReport:
    """Assemble one combined report from this session's active steering claims.

    Every section reads through one :class:`FleetReportReads`, so two seats
    held on the same project compose from one read of that project's facts
    and one read of each repository's merge queue. The request object is
    created here and dropped with the reply. ``reuse_schedule`` lets a pull
    take a schedule pass a few seconds old.
    """
    now = parse_instant(now)
    from yoke_core.domain.steering_report_read_connection import ReportReadConnection

    conn = ReportReadConnection(conn)
    reads = FleetReportReads(
        include_inventory=include_inventory, reuse_schedule=reuse_schedule
    )
    sections: list[ScopedFleetReport] = []
    for claim in list_session_claims(conn, session_id=session_id, active_only=True):
        scope = dict(claim.get("scope") or {})
        raw = scope.get("project_id")
        if raw is None:
            continue
        held_project = int(raw)
        if project_id is not None and held_project != int(project_id):
            continue
        staffing_minutes, idle_minutes = reads.cached(
            ("report_thresholds", held_project),
            lambda project=held_project: (
                _policy_minutes(
                    conn,
                    project,
                    "steering_report_staffing_minutes",
                    DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
                ),
                _policy_minutes(
                    conn,
                    project,
                    "steering_report_idle_minutes",
                    DEFAULT_STEERING_REPORT_IDLE_MINUTES,
                ),
            ),
        )
        report = fleet_report.compose_report(
            conn,
            project_id=held_project,
            session_id=session_id,
            staffing_after_seconds=60 * staffing_minutes,
            idle_after_seconds=60 * idle_minutes,
            now=now,
            scope=scope,
            reads=reads,
        )
        sections.append(
            ScopedFleetReport(
                descriptor=steering_scope_descriptor(conn, scope, reads),
                report=report,
            )
        )
    sections.sort(
        key=lambda section: (not section.report.actionable, section.descriptor)
    )
    from yoke_core.domain.steering_fleet_report_labels import session_labels

    labels = session_labels(
        conn, tuple(s.report for s in sections), reads.machine_names(conn)
    )
    sections = [
        replace(s, report=replace(s.report, session_labels=labels)) for s in sections
    ]
    project_ids = [int(section.report.project_id) for section in sections]
    return CombinedFleetReport(
        composed_at=now,
        sections=tuple(sections),
        unattended=unattended_linked_items(conn, project_ids),
        slow_paths=(read_slow_paths(conn, project_ids=sorted(set(project_ids)), now=now)
                    if include_inventory else ()),
    )


def _level_lines(reports: tuple[FleetReport, ...]) -> list[str]:
    """Each distinct level readout once: scopes on one project share it."""
    names = {key: value for report in reports for key, value in report.machine_names}
    seen: list[LevelReadout] = []
    headings: set[str] = set()
    lines: list[str] = []
    for report in reports:
        if report.levels is None or report.levels in seen:
            continue
        seen.append(report.levels)
        block = level_readout_lines(report.levels, machine_names=names)
        if report.levels.source in headings:
            block = [f"  placement for project {report.project_id}", *block[1:]]
        headings.add(report.levels.source)
        lines.extend(["", *block])
    return lines


def combined_body(combined: CombinedFleetReport) -> str:
    """One envelope: per-scope facts, then one machine block per machine_id.

    Shared machine facts sit after the scope sections so available work
    still leads. Blocks are keyed by machine_id from the reports, never by
    comparing rendered text.
    """
    reports = tuple(section.report for section in combined.sections)
    shared = rows_per_section(reports)
    parts = [
        REPORT_BEGIN,
        f"composed {combined.composed_at} · {len(combined.sections)} held scopes",
        COMBINED_PREAMBLE,
        "",
    ]
    if combined.unattended:
        parts.extend(
            [
                "## unattended linked work",
                *(f"  {row.finding}" for row in combined.unattended),
                "",
            ]
        )
    parts.extend(slow_path_lines(combined.slow_paths))
    projects: set[int] = set()
    for section, rows in zip(combined.sections, shared):
        first = section.report.project_id not in projects
        projects.add(section.report.project_id)
        body = scope_inner_body(section.report, rows, include_header=first)
        parts.extend([f"## {section.descriptor}", *([body] if body else []), ""])
    parts.extend(fleet_shared_lines(reports))
    parts.extend(machine_shared_lines(reports, now=combined.composed_at))
    parts.extend(_level_lines(reports))
    if parts[-1] != "":
        parts.append("")
    parts.append(REPORT_END)
    return "\n".join(parts)


def combined_dict(combined: CombinedFleetReport) -> dict[str, Any]:
    """Machine-readable projection of the combined report."""
    from yoke_core.domain.steering_fleet_report_hook_digest import (
        combined_hook_digest,
    )

    return {
        "composed_at": combined.composed_at,
        "actionable": combined.actionable,
        "fingerprint": combined.fingerprint(),
        "unattended": [row.finding for row in combined.unattended],
        "slow_paths": [row.to_dict() for row in combined.slow_paths],
        "scopes": [
            {"descriptor": section.descriptor, **report_dict(section.report)}
            for section in combined.sections
        ],
        "body": combined_body(combined),
        "digest": combined_hook_digest(combined),
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
