"""Assemble one doctor run's roster and split it by applicability.

Both runners — the local CLI and the ``doctor.run.run`` handler — build the
roster here so a check's fate does not depend on which door the run came
through. The roster is the engine's registered checks plus whatever the
target project declares in its own ``.yoke/doctor/`` folder; the split
separates the checks that apply to this project and runtime from the ones
that do not, each with the reason it does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Tuple

from yoke_core.engines.doctor_applicability import (
    DoctorContext,
    NOT_APPLICABLE,
    not_applicable_reason,
)
from yoke_core.engines.doctor_applicability_declarations import applicability_for
from yoke_core.engines.doctor_project_checks import (
    DiscoveryFailure,
    discover_project_checks,
)
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _should_run_hc,
)


@dataclass
class Roster:
    """The checks one run will execute, and the ones it will not."""

    applicable: List[HealthCheck] = field(default_factory=list)
    not_applicable: List[Tuple[HealthCheck, str]] = field(default_factory=list)
    discovery_failures: List[DiscoveryFailure] = field(default_factory=list)

    @property
    def slugs(self) -> List[str]:
        return [hc.slug for hc in self.applicable]


def resolve_applicability(hc: HealthCheck):
    """The check's own declaration, falling back to the registered table.

    Engine checks declare through the slug-keyed table; a project-local check
    carries its declaration on the row itself.
    """
    return hc.applicability or applicability_for(hc.slug)


def build_roster(
    checks: Iterable[HealthCheck],
    args: DoctorArgs,
    context: DoctorContext,
    *,
    include_project_checks: bool = True,
) -> Roster:
    """Split the roster for *context* into applicable and not-applicable.

    Scope selection (``--quick`` / ``--only``) still decides which checks the
    run asked for; applicability then decides which of those can honestly
    answer. A check the operator named explicitly with ``--only`` is still
    reported as not-applicable rather than silently dropped.
    """
    roster = Roster()
    registered = list(checks)
    if include_project_checks:
        discovery = discover_project_checks(context.source_checkout)
        registered.extend(discovery.checks)
        roster.discovery_failures.extend(discovery.failures)
    for hc in registered:
        if not _should_run_hc(hc.slug, args):
            continue
        reason = not_applicable_reason(resolve_applicability(hc), context)
        if reason is None:
            roster.applicable.append(hc)
        else:
            roster.not_applicable.append((hc, reason))
    return roster


def record_not_applicable(roster: Roster, rec: RecordCollector) -> None:
    """Record one :data:`NOT_APPLICABLE` result per out-of-scope check."""
    for hc, reason in roster.not_applicable:
        rec.record(f"HC-{hc.slug}", hc.name, NOT_APPLICABLE, reason)


def record_discovery_failures(roster: Roster, rec: RecordCollector) -> None:
    """Record a FAIL for every project-local check module that would not load.

    A project check that cannot be imported is a finding about the project,
    not a reason to keep quiet.
    """
    for failure in roster.discovery_failures:
        rec.record(
            "HC-project-check-discovery",
            "Project-local check module import",
            "FAIL",
            f"{failure.path} failed to import: {failure.error}. "
            "Fix the module or remove it from the project's .yoke/doctor/ "
            "folder; a check that cannot load never runs.",
        )


__all__ = [
    "Roster",
    "build_roster",
    "record_discovery_failures",
    "record_not_applicable",
    "resolve_applicability",
]
