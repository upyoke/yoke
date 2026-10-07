"""Read a project's migration models together with their declared fleets.

One reader for the fleet preflight and the release gate, through the
registered capability read, so a gate on a relayed control plane and a
preflight beside a local one read the same two documents. An unreadable or
invalid declaration fails closed: guessing it would report a release as
carrying nothing to rehearse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from yoke_core.domain import migration_model_fleet as fleets

#: Registered read serving one capability settings document.
CAPABILITY_FUNCTION_ID = "projects.capability_settings.get"


@dataclass(frozen=True)
class DeclaredFleets:
    """A project's migration models and the fleet each one declares."""

    models: Dict[str, Any] = field(default_factory=dict)
    default_model: str = ""
    fleets: Dict[str, Any] = field(default_factory=dict)

    def fleet(self, model_name: str) -> Optional[Dict[str, Any]]:
        """The model's declared fleet, or ``None`` when it declares none."""
        declared = self.fleets.get(model_name)
        return dict(declared) if isinstance(declared, Mapping) else None


def read_declared(project: str) -> Tuple[DeclaredFleets, str]:
    """The project's models and fleets, or why they could not be read.

    A project with no ``migration_model`` capability returns an empty
    declaration and no error: it governs no database migrations.
    """
    from yoke_core.domain.migration_model_capability_validation import (
        MigrationModelCapabilityError,
        validate as validate_models,
    )

    models_doc, error = _read_document(
        project, "migration_model", validate_models, MigrationModelCapabilityError
    )
    if error or not models_doc:
        return DeclaredFleets(), error
    fleet_doc, error = _read_document(
        project,
        fleets.CAPABILITY_TYPE,
        fleets.validate_capability,
        fleets.MigrationFleetError,
    )
    if error:
        return DeclaredFleets(), error
    models = dict(models_doc.get("models") or {})
    declared = dict((fleet_doc or {}).get("models") or {})
    stray = sorted(set(declared) - set(models))
    if stray:
        return DeclaredFleets(), (
            f"project {project!r} declares a {fleets.CAPABILITY_TYPE} for "
            f"{stray}, which its migration_model does not declare "
            f"(declared models: {sorted(models)}); correct or remove those "
            f"entries with `yoke projects capability-settings merge --project "
            f"{project} --cap-type {fleets.CAPABILITY_TYPE}`"
        )
    return (
        DeclaredFleets(
            models=models,
            default_model=str(models_doc.get("default_model") or ""),
            fleets=declared,
        ),
        "",
    )


def _read_document(
    project: str,
    cap_type: str,
    validate: Callable[[Any], Dict[str, Any]],
    invalid: type,
) -> Tuple[Dict[str, Any], str]:
    """One validated capability document; ``({}, "")`` when it is absent."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    unknown = f"could not read the {cap_type} capability of project {project!r}"
    try:
        response = call_dispatcher(
            function_id=CAPABILITY_FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"project": project, "cap_type": cap_type},
        )
    except Exception as exc:  # noqa: BLE001 - unreadable declaration fails closed
        return {}, f"{unknown}: {exc}"
    if not response.success:
        if response.error is not None and response.error.code == "not_found":
            return {}, ""
        detail = (
            response.error.message
            if response.error is not None
            else "capability read refused"
        )
        return {}, f"{unknown}: {detail}"
    result = response.result if isinstance(response.result, Mapping) else {}
    try:
        return validate(json.loads(str(result.get("settings_json") or ""))), ""
    except (invalid, TypeError, ValueError) as exc:
        return {}, f"{unknown}: {exc}"


__all__ = ["CAPABILITY_FUNCTION_ID", "DeclaredFleets", "read_declared"]
