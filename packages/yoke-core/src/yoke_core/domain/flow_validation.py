"""Stage-shape validation for deployment flows.

Validates the JSON ``stages`` array carried by ``deployment_flows`` rows.
Every stage is a named step the pipeline runs: a ``name`` plus a
``step_runner`` drawn from :data:`VALID_STEP_RUNNERS`.
"""

from __future__ import annotations

import json
from typing import Any

VALID_STEP_RUNNERS = frozenset(
    {
        "auto",
        "health-check",
        "warm-up",
        "environment-activate",
        "core-container-deploy",
        "ephemeral-deploy",
        "ephemeral-teardown",
        "ephemeral-verify",
        "human-approval",
        "github-actions-workflow",
    }
)

APPROVAL_ROLES = frozenset({"owner", "operator", "admin"})

MISSING_STAGE_APPROVALS = (
    "human-approval stage {name!r} has no approvers; set "
    "approvals.roles and/or approvals.actors on the stage "
    "(Delivery → Flows editor, or yoke deployment-flows update-stages)"
)


def parse_stage_approvals(
    raw: Any,
    *,
    path: str,
) -> tuple[list[str], list[int]]:
    """Return unique roles and named actor ids from one stage approvals object."""
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object with roles and actors")
    extra = set(raw) - {"roles", "actors"}
    if extra:
        raise ValueError(f"{path} has unknown fields: {sorted(extra)}")
    roles_raw = raw.get("roles", [])
    actors_raw = raw.get("actors", [])
    if not isinstance(roles_raw, list) or not isinstance(actors_raw, list):
        raise ValueError(f"{path} roles and actors must be arrays")
    roles = [str(value) for value in roles_raw]
    if len(roles) != len(set(roles)):
        raise ValueError(f"{path}.roles must be unique")
    unknown = set(roles) - APPROVAL_ROLES
    if unknown:
        raise ValueError(f"{path}.roles has unknown values: {sorted(unknown)}")
    actors: list[int] = []
    for value in actors_raw:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{path}.actors must be unique positive integer actor ids")
        actors.append(int(value))
    if len(actors) != len(set(actors)):
        raise ValueError(f"{path}.actors must be unique positive integer actor ids")
    if not roles and not actors:
        raise ValueError(f"{path} must name at least one role or actor")
    return roles, sorted(set(actors))


def require_human_approval_addresses(stages_json: str) -> None:
    """Refuse a write whose human-approval stages omit who may approve."""
    stages = json.loads(stages_json)
    if not isinstance(stages, list):
        return
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        if stage.get("step_runner") != "human-approval":
            continue
        name = str(stage.get("name") or f"stage {index}")
        if "approvals" not in stage:
            raise ValueError(MISSING_STAGE_APPROVALS.format(name=name))
        parse_stage_approvals(
            stage.get("approvals"),
            path=f"stage {index} ({name}) approvals",
        )


def validate_stages(stages_json: str) -> None:
    """Validate stages JSON.

    Every stage carries a ``name`` and a ``step_runner`` from the
    VALID_STEP_RUNNERS vocabulary. When a stage carries ``approvals``,
    the address must be well-formed; presence is required on operator
    writes via :func:`require_human_approval_addresses`.
    """
    try:
        stages = json.loads(stages_json)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"stages is not valid JSON: {e}")

    if not isinstance(stages, list):
        raise ValueError("stages must be a JSON array")
    if not stages:
        raise ValueError("stages array must not be empty")

    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise ValueError(f"stage {i} is not an object")

        if "name" not in stage:
            raise ValueError(f'stage {i} missing required field "name"')
        if "step_runner" not in stage:
            raise ValueError(f'stage {i} missing required field "step_runner"')
        if stage["step_runner"] not in VALID_STEP_RUNNERS:
            raise ValueError(
                f'stage {i} has invalid step_runner "{stage["step_runner"]}". '
                f"Must be one of: {' '.join(sorted(VALID_STEP_RUNNERS))}"
            )
        if "wait_for_ci" in stage:
            if stage["step_runner"] != "github-actions-workflow":
                raise ValueError(
                    f'stage {i} carries "wait_for_ci" but step_runner '
                    'is not "github-actions-workflow"'
                )
            if not isinstance(stage["wait_for_ci"], bool):
                raise ValueError(f'stage {i} field "wait_for_ci" must be a boolean')
        if "approvals" in stage:
            parse_stage_approvals(
                stage["approvals"],
                path=f"stage {i} ({stage.get('name')}) approvals",
            )
