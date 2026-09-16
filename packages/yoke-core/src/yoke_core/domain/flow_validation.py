"""Stage-shape validation for deployment flows.

Validates the JSON ``stages`` array carried by ``deployment_flows`` rows.
Every stage is a named step the pipeline runs: a ``name`` plus a
``step_runner`` drawn from :data:`VALID_STEP_RUNNERS`.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.approval_policy import (
    ApprovalPolicy,
    parse_approval_policy,
)
from yoke_core.domain.deployment_flow_policy import (
    QA_STEP_RUNNER,
    validate_release_stage_policy,
)

WORKFLOW_STEP_RUNNER = "github-actions-workflow"

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
        WORKFLOW_STEP_RUNNER,
        QA_STEP_RUNNER,
    }
)

MISSING_STAGE_APPROVALS = (
    "human-approval stage {name!r} has no approvers; set "
    "approvals.roles and/or approvals.actors on the stage "
    "(Delivery → Flows editor, or yoke deployment-flows update-stages)"
)

#: Runner fields a github-actions-workflow stage declares beside ``name``
#: and ``step_runner``, named in the repair so a nested stage can be
#: flattened in one edit.
WORKFLOW_STAGE_RUNNER_FIELDS = (
    "workflow",
    "ref",
    "inputs",
    "wait_for_ci",
    "dispatch_correlation_input",
)

NESTED_STAGE_CONFIG = (
    "stage {index} ({name!r}) wraps its runner fields in a nested "
    '"config" object; a stored stage declares them top-level, beside '
    '"name" and "step_runner", because that is where the pipeline reads '
    "them. A nested stage validates and then refuses at dispatch with "
    'nothing to run. Lift the contents of "config" up into the stage '
    "and delete the empty object."
)

MISSING_STAGE_WORKFLOW = (
    'stage {index} ({name!r}) has step_runner "{runner}" but declares no '
    'top-level "workflow", so there is no workflow to trigger and the '
    "stage would refuse at dispatch after the run had already started. "
    "Declare workflow on the stage ({fields} belong there too)."
)


def parse_stage_approvals(raw: Any, *, path: str) -> ApprovalPolicy:
    """Return the approval policy one human-approval stage declares."""
    return parse_approval_policy(raw, path=path)


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


def require_top_level_runner_fields(stages_json: str) -> None:
    """Refuse an operator write whose stages nest their runner fields.

    The pipeline reads a stage's runner fields off the stage itself, so a
    stage that wraps them in a ``config`` object passes every shape check
    and then refuses mid-run with no workflow to trigger — after the run
    has started and the earlier stages have already deployed. Checking at
    the write, and in the registered validation preview, is what turns that
    into a refusal the operator can act on. Stored stages are not
    revalidated: this is a write-path requirement, like
    :func:`require_human_approval_addresses`.
    """
    stages = json.loads(stages_json)
    if not isinstance(stages, list):
        return
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        name = str(stage.get("name") or f"stage {index}")
        if "config" in stage:
            raise ValueError(NESTED_STAGE_CONFIG.format(index=index, name=name))
        if stage.get("step_runner") != WORKFLOW_STEP_RUNNER:
            continue
        workflow = stage.get("workflow")
        if not isinstance(workflow, str) or not workflow.strip():
            raise ValueError(
                MISSING_STAGE_WORKFLOW.format(
                    index=index,
                    name=name,
                    runner=WORKFLOW_STEP_RUNNER,
                    fields=", ".join(WORKFLOW_STAGE_RUNNER_FIELDS[1:]),
                )
            )


def validate_stages(stages_json: str) -> None:
    """Validate stages JSON.

    Every stage carries a ``name`` and a ``step_runner`` from the
    VALID_STEP_RUNNERS vocabulary. When a stage carries ``approvals``,
    the address must be well-formed; presence is required on operator
    writes via :func:`require_human_approval_addresses`, and top-level
    runner fields via :func:`require_top_level_runner_fields`.
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
            if stage["step_runner"] != WORKFLOW_STEP_RUNNER:
                raise ValueError(
                    f'stage {i} carries "wait_for_ci" but step_runner '
                    f'is not "{WORKFLOW_STEP_RUNNER}"'
                )
            if not isinstance(stage["wait_for_ci"], bool):
                raise ValueError(f'stage {i} field "wait_for_ci" must be a boolean')
        if "approvals" in stage:
            parse_stage_approvals(
                stage["approvals"],
                path=f"stage {i} ({stage.get('name')}) approvals",
            )
    validate_release_stage_policy(stages)
