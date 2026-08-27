"""Select machine-local Doctor checks for an HTTPS run scope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_contracts.install_binding import is_yoke_source_checkout
from yoke_core.engines.doctor_applicability import DoctorContext, RUNTIME_LOCAL
from yoke_core.engines.doctor_applicability_declarations import (
    local_runtime_slugs,
    source_checkout_slugs,
)
from yoke_core.engines.doctor_https_compose import checkout_root_for_project
from yoke_core.engines.doctor_registry import HEALTH_CHECKS
from yoke_core.engines.doctor_report import DoctorArgs
from yoke_core.engines.doctor_roster import build_roster


def requested_local_machine_slugs(
    payload: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    """Return local-runtime and source-checkout slugs in *payload*'s scope.

    The shared Doctor scope selector keeps ``--quick`` and ``--only``
    behavior identical to the relayed runner while the client recovers from
    a control-plane transport failure.
    """
    project = str(payload.get("project") or "")
    checkout = checkout_root_for_project(project)
    self_names = (
        frozenset({project})
        if checkout is not None and is_yoke_source_checkout(checkout)
        else frozenset()
    )
    args = DoctorArgs(
        only=str(payload["only"]) if payload.get("only") else None,
        quick=bool(payload.get("quick")),
        project=project,
        fix=bool(payload.get("fix")),
        runtime=RUNTIME_LOCAL,
    )
    runtime_candidates = local_runtime_slugs()
    source_candidates = source_checkout_slugs()
    candidate_slugs = runtime_candidates | source_candidates
    roster = build_roster(
        (hc for hc in HEALTH_CHECKS if hc.slug in candidate_slugs),
        args,
        DoctorContext(
            project=project,
            runtime=RUNTIME_LOCAL,
            self_project=project if self_names else None,
            self_project_names=self_names,
            source_checkout=checkout,
        ),
        include_project_checks=False,
    )
    selected = set(roster.slugs)
    return (
        sorted(selected & runtime_candidates),
        sorted(selected & source_candidates),
    )


__all__ = ["requested_local_machine_slugs"]
