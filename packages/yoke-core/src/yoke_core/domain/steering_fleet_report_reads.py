"""What one report request reads once and every held scope then shares.

A seat holding several steering claims composes several sections from one
control-plane state. The schedule, the claim holders, the delivery-plane
detectors and the machine facts are the same answer for every scope in the
same project, and the machine facts are the same answer across projects
too; only membership filtering differs, and filtering is something a
section does to facts it was handed rather than a reason to read them
again.

So the project-wide facts are a value — :class:`ProjectFleetFacts` — read
once per project and handed to each scope, and :class:`FleetReportReads`
is the request that holds them. Its lifetime is one request: the composer
creates it, the reply is rendered from it, and it is discarded. Nothing is
remembered between requests, so every report still reads live state and no
authorization decision outlives the read it was made for. ``session_id``
and ``now`` are fixed for a request, which is why the memo keys carry only
the project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from yoke_core.domain.machine_registry import machine_names
from yoke_core.domain.merge_queue_read_reuse import MergeQueueReads
from yoke_core.domain.session_launch_capacity import MachineCapacity
from yoke_core.domain.steering_fleet_report_abandoned import (
    AbandonedLaunch,
    abandoned_launches,
)
from yoke_core.domain.steering_fleet_report_available import (
    FrontierEntry,
    scope_candidates,
)
from yoke_core.domain.steering_fleet_report_capacity import (
    SessionCount,
    SurfaceReadiness,
    launchable_surfaces,
    live_launch_origin_counts,
    live_session_counts,
    machine_capacities,
)
from yoke_core.domain.steering_fleet_report_deployment_runs import (
    DeploymentRunProgress,
    run_progress,
)
from yoke_core.domain.steering_fleet_report_detectors import (
    UnregisteredLaunch,
    unregistered_launches,
)
from yoke_core.domain.steering_fleet_report_landed_open import (
    LandedItem,
    landed_without_closeout,
)
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder, claim_holders
from yoke_core.domain.steering_fleet_report_limits import (
    MachinePlanLimit,
    load_plan_limits,
)
from yoke_core.domain.steering_fleet_report_native_models import (
    MachineNativeModels,
    load_native_models,
)
from yoke_core.domain.steering_fleet_report_relay_health import (
    RelayHealthCondition,
    relay_health_conditions,
)
from yoke_core.domain.steering_fleet_report_stranded import (
    StrandedSession,
    stranded_sessions,
)
from yoke_core.domain.steering_fleet_report_undelivered import (
    UndeliveredMessages,
    undelivered_messages,
)
from yoke_core.domain.steering_fleet_report_vendor_errors import (
    VendorErrorSession,
    vendor_error_sessions,
)


@dataclass(frozen=True)
class ProjectFleetFacts:
    """One project's report inputs, before any scope narrows them."""

    available: tuple[FrontierEntry, ...]
    holders: tuple[ClaimHolder, ...]
    undelivered: tuple[UndeliveredMessages, ...]
    unregistered_launches: tuple[UnregisteredLaunch, ...]
    abandoned_launches: tuple[AbandonedLaunch, ...]
    landed_open: tuple[LandedItem, ...]
    #: Live deployment runs. A run is a delivery-plane fact with members
    #: rather than an item, so no scope narrows it.
    deployment_runs: tuple[DeploymentRunProgress, ...]
    vendor_errors: tuple[VendorErrorSession, ...]
    stranded: tuple[StrandedSession, ...]
    launchable: tuple[SurfaceReadiness, ...]
    session_counts: tuple[SessionCount, ...]
    origin_counts: tuple[tuple[str, int], ...]
    plan_limits: tuple[MachinePlanLimit, ...]
    native_models: tuple[MachineNativeModels, ...]
    machine_capacity: tuple[MachineCapacity, ...]
    relay_health: tuple[RelayHealthCondition, ...]
    machine_names: Mapping[str, str]


def read_project_facts(
    conn: Any,
    *,
    project_id: int,
    session_id: str,
    now: str,
    registered_names: Mapping[str, str],
) -> ProjectFleetFacts:
    """Read every project-wide fact one report scope is composed from.

    The claim holders are read once and handed on. The landed section needs
    the same answer — close-out is a claim-holding step — and when it asked
    the database itself it got a narrower one that knew nothing about who was
    parked, which is how a healthy wait came to print a close-out command.
    """
    holders = claim_holders(conn, project_id=project_id, now=now)
    plan_limits = load_plan_limits(
        conn, project_id=project_id, now=now, registered_names=registered_names
    )
    return ProjectFleetFacts(
        available=scope_candidates(conn, project_id=project_id, session_id=session_id),
        holders=holders,
        undelivered=undelivered_messages(conn, project_id=project_id, now=now),
        unregistered_launches=unregistered_launches(
            conn, project_id=project_id, now=now
        ),
        abandoned_launches=abandoned_launches(conn, project_id=project_id, now=now),
        landed_open=landed_without_closeout(
            conn, project_id=project_id, now=now, holders=holders
        ),
        deployment_runs=run_progress(conn, project_id=project_id, now=now),
        vendor_errors=vendor_error_sessions(conn, project_id=project_id, now=now),
        stranded=stranded_sessions(
            conn, project_id=project_id, now=now, limits=plan_limits
        ),
        launchable=launchable_surfaces(conn, project_id=project_id, now=now),
        session_counts=live_session_counts(conn, project_id=project_id),
        origin_counts=live_launch_origin_counts(conn, project_id=project_id),
        plan_limits=plan_limits,
        native_models=load_native_models(
            conn, project_id=project_id, now=now, registered_names=registered_names
        ),
        machine_capacity=machine_capacities(conn, project_id=project_id, now=now),
        relay_health=relay_health_conditions(conn, project_id=project_id, now=now),
        machine_names=registered_names,
    )


@dataclass
class FleetReportReads:
    """One report request's shared reads, discarded with the request."""

    landings: MergeQueueReads = field(default_factory=MergeQueueReads)
    _memo: dict[tuple[Any, ...], Any] = field(default_factory=dict)

    def cached(self, key: tuple[Any, ...], factory: Callable[[], Any]) -> Any:
        """Return ``factory()`` for ``key``, evaluating it once per request."""
        if key not in self._memo:
            self._memo[key] = factory()
        return self._memo[key]

    def machine_names(self, conn: Any) -> Mapping[str, str]:
        """Registered machine names, which no scope narrows."""
        return self.cached(("machine_names",), lambda: machine_names(conn))

    def project_facts(
        self,
        conn: Any,
        *,
        project_id: int,
        session_id: str,
        now: str,
    ) -> ProjectFleetFacts:
        """This project's unfiltered facts, read on the first scope that asks."""
        return self.cached(
            ("project_facts", int(project_id)),
            lambda: read_project_facts(
                conn,
                project_id=int(project_id),
                session_id=session_id,
                now=now,
                registered_names=self.machine_names(conn),
            ),
        )


__all__ = [
    "FleetReportReads",
    "ProjectFleetFacts",
    "read_project_facts",
]
