"""Project-selection fields shared by target resolution and refusal composition."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest

# Functions whose target project lives in payload ``slug``, ``project``, or
# ``scope``; a target-ref hint must agree with that payload authority.
PAYLOAD_NAMED_PROJECT_FUNCTIONS = frozenset(
    {
        "ephemeral_env.create",
        "ephemeral_env.get",
        "projects.update",
        "projects.retire",
        "projects.unretire",
        "projects.capability_settings.get",
        "projects.level_summary.get",
        "projects.capability_settings.set",
        "projects.capability_settings.merge",
        "projects.capability_settings.remove",
        "projects.environment_settings.get",
        "projects.environment_settings.merge",
        "projects.infrastructure.list",
        "projects.environment.list",
        "packs.list",
        "packs.bundle.get",
        "packs.bundle.render",
        "packs.project.report",
        "board.data.get",
        "board.rebuild.run",
    }
)


def project_selection_missing(request: FunctionCallRequest) -> bool:
    """Missing selection excludes supplied record identities, even unresolved ones."""
    target = request.target.model_dump(exclude={"kind"}, exclude_none=True)
    if any(str(value).strip() for value in target.values()):
        return False
    # An unresolved record must retain the non-disclosing authorization denial.
    # IDs identify a subject even when zero, malformed, or absent from storage.
    if any(
        (key == "id" or key.endswith("_id"))
        and value is not None
        and str(value).strip()
        for key, value in request.payload.items()
    ):
        return False
    keys = ["project"]
    if request.function in PAYLOAD_NAMED_PROJECT_FUNCTIONS:
        keys.extend(("slug", "scope"))
    if request.function == "ephemeral_env.update":
        keys.append("env_id")
    if any(str(request.payload.get(key) or "").strip() for key in keys):
        return False
    supplied_target = request.payload.get("target")
    return not isinstance(supplied_target, dict) or not supplied_target
