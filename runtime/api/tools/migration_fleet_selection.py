"""Turn one project's declared migration-model fleet into a rehearsal.

The fleet preflight is one path for every project: it reads the fleet the
model declares in the project's ``migration_fleet`` capability (see
:mod:`yoke_core.domain.migration_model_fleet`) and
binds the generic rehearsal kernel to it. An ``engine_tenants`` fleet uses the
engine's own tenant roster and boot convergence; a ``named_databases`` fleet
uses the databases and boot command the project declares, run from that
project's checkout on this machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Tuple

from yoke_core.domain import migration_model_fleet as fleets
from yoke_core.domain.migration_fleet_preflight import RehearsalPlan


@dataclass(frozen=True)
class FleetTarget:
    """Everything one preflight run needs to rehearse one model's fleet."""

    project: str
    model_name: str
    plan: RehearsalPlan
    databases: Callable[[Callable[[str], str]], List[str]]
    schema_shape_digest: Callable[[], str]


def resolve(
    project: str,
    model_name: Optional[str] = None,
    *,
    checkout: Optional[Path] = None,
) -> Tuple[Optional[FleetTarget], str]:
    """The project's model fleet as a rehearsal, or why there is none to run."""
    from yoke_core.domain.migration_model_fleet_read import read_declared

    declared, unreadable = read_declared(project)
    if unreadable:
        return None, unreadable
    models: Mapping[str, Any] = declared.models
    if not models:
        return None, (
            f"project {project!r} declares no migration_model capability, so "
            "it has no governed databases to rehearse"
        )
    name = model_name or declared.default_model
    if not name:
        return None, (
            f"project {project!r} declares no default_model; name the model "
            f"with --model (one of {sorted(models)})"
        )
    model = models.get(name)
    if model is None:
        return None, (
            f"project {project!r} declares no migration model {name!r}; "
            f"declared: {sorted(models)}"
        )
    fleet = declared.fleet(name)
    if fleet is None:
        return None, fleets.undeclared_refusal(project, name)
    if fleet["kind"] == fleets.FLEET_NONE:
        return None, (
            f"migration model {name!r} of project {project!r} declares no live "
            f"fleet ({fleet['reason']}); there is nothing to rehearse and its "
            "release gate requires no receipt"
        )
    if fleet["kind"] == fleets.FLEET_ENGINE_TENANTS:
        return _engine_tenants(project, name), ""
    return _named_databases(project, name, model, fleet, checkout)


def _engine_tenants(project: str, model_name: str) -> FleetTarget:
    from yoke_core.domain.schema_shape_source import digest_schema_shape
    from runtime.api.tools import yoke_migration_fleet

    return FleetTarget(
        project=project,
        model_name=model_name,
        plan=yoke_migration_fleet.rehearsal_plan(),
        databases=lambda dsn_for: yoke_migration_fleet.tenant_databases(dsn_for),
        schema_shape_digest=digest_schema_shape,
    )


def _named_databases(
    project: str,
    model_name: str,
    model: Mapping[str, Any],
    fleet: Mapping[str, Any],
    checkout: Optional[Path],
) -> Tuple[Optional[FleetTarget], str]:
    from yoke_core.domain.migration_fleet_declared_plan import declared_plan
    from yoke_core.domain.migration_history import HistoryError
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_slug,
    )

    checkout = checkout or checkout_for_project_slug(project)
    if checkout is None:
        return None, (
            f"project {project!r} has no checkout registered on this machine, "
            "and its fleet converges through that checkout's own boot command. "
            "Pass --checkout <path>, or register it under the connection the "
            "preflight runs with: yoke project register <checkout> "
            "--project-id <project-id>"
        )
    try:
        plan = declared_plan(model, fleet, checkout)
    except HistoryError as exc:
        return None, f"migration history of project {project!r} is unreadable: {exc}"
    names = list(fleet["names"])

    def databases(_dsn_for: Callable[[str], str]) -> List[str]:
        for database in names:
            print(f"  roster {database}: member (declared by model {model_name})")
        return names

    return (
        FleetTarget(
            project=project,
            model_name=model_name,
            plan=plan,
            databases=databases,
            schema_shape_digest=lambda: fleets.schema_shape_digest(
                fleet, Path(checkout)
            ),
        ),
        "",
    )


__all__ = ["FleetTarget", "resolve"]
