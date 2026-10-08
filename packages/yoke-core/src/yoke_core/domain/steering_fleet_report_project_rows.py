"""Rows that belong to a project, shown once however many seats read them.

A session can hold several steering seats on one project — the whole project
and a document inside it, or several documents. Every seat composes the same
deployment runs and launch failures, and a whole-project seat lists every
landed item and undelivered envelope a document seat lists too. Rendering
those per seat printed one run block once per held seat.

So these sections render once per project: under the first held seat of that
project, merged across every seat of it, and omitted from the rest. A seat's
own section keeps only what is specific to the seat — its available work, its
holders, and their detectors.

A landed item already delivering in a listed run is that run's member, so it
is not listed a second time as landed without close-out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Sequence, TypeVar

from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT

if TYPE_CHECKING:  # pragma: no cover - annotation only, no import cycle
    from yoke_core.domain.steering_fleet_report import FleetReport
    from yoke_core.domain.steering_fleet_report_abandoned import AbandonedLaunch
    from yoke_core.domain.steering_fleet_report_deployment_runs import (
        DeploymentRunProgress,
    )
    from yoke_core.domain.steering_fleet_report_detectors import UnregisteredLaunch
    from yoke_core.domain.steering_fleet_report_landed_open import LandedItem
    from yoke_core.domain.steering_fleet_report_undelivered import (
        UndeliveredMessages,
    )

T = TypeVar("T")


@dataclass(frozen=True)
class ProjectRows:
    """One project's project-wide sections; empty for a seat that omits them."""

    deployment_runs: tuple[DeploymentRunProgress, ...] = ()
    landed_open: tuple[LandedItem, ...] = ()
    undelivered: tuple[UndeliveredMessages, ...] = ()
    unregistered_launches: tuple[UnregisteredLaunch, ...] = ()
    abandoned_launches: tuple[AbandonedLaunch, ...] = ()

    @classmethod
    def of(cls, report: FleetReport) -> ProjectRows:
        """A single report's own rows, for a report rendered on its own."""
        return merged_project_rows((report,))

    def listed_run_ids(self) -> set[str]:
        return {run.run_id for run in self.deployment_runs[:SECTION_LIMIT]}

    def visible_landed(self) -> tuple[LandedItem, ...]:
        """Landed items not already shown as a listed run's member."""
        listed = self.listed_run_ids()
        return tuple(
            entry for entry in self.landed_open if entry.custody_run_id not in listed
        )


def _unique(rows: Iterable[T], key: Callable[[T], Any]) -> tuple[T, ...]:
    seen: set[Any] = set()
    kept = []
    for row in rows:
        if key(row) not in seen:
            seen.add(key(row))
            kept.append(row)
    return tuple(kept)


def merged_project_rows(reports: Sequence[FleetReport]) -> ProjectRows:
    """Every seat's project-wide rows for one project, each row once."""
    first = reports[0]
    return ProjectRows(
        deployment_runs=first.deployment_runs,
        landed_open=_unique(
            (entry for report in reports for entry in report.landed_open),
            lambda entry: entry.item_id,
        ),
        undelivered=_unique(
            (entry for report in reports for entry in report.undelivered),
            lambda entry: entry.session_id,
        ),
        unregistered_launches=first.unregistered_launches,
        abandoned_launches=first.abandoned_launches,
    )


def rows_per_section(reports: Sequence[FleetReport]) -> list[ProjectRows]:
    """For each report in order: its project's merged rows, or empty.

    The first report of each project carries the merged rows; every later
    report of the same project carries an empty set, so the sections render
    nothing there.
    """
    by_project: dict[int, list[FleetReport]] = {}
    for report in reports:
        by_project.setdefault(int(report.project_id), []).append(report)
    rendered: set[int] = set()
    rows = []
    for report in reports:
        project = int(report.project_id)
        if project in rendered:
            rows.append(ProjectRows())
            continue
        rendered.add(project)
        rows.append(merged_project_rows(by_project[project]))
    return rows


__all__ = ["ProjectRows", "merged_project_rows", "rows_per_section"]
