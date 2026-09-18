"""Which execution targets a Machine QA case may carry, and why one is refused.

A QA case is executed against exactly one immutable execution-target
snapshot, and the server stamps that snapshot onto the requirement when the
case is materialized. Two of the registered snapshot shapes are executable by
a Test Machine: the *environment* snapshot a plan resolves from its own bound
environment, and the *deployment* snapshot a deployment run resolves from the
receipt its deploying stage wrote. The third registered shape, the *project*
snapshot, is command-runner-only and carries no environment at all, so it
never reaches a machine contract.

The check here exists because the contract is digest-bound: whatever the
target says is what the runner will observe and what the evidence will claim.
So it verifies the target still belongs to the case's own project and tenant
and still names somewhere to look — and when it does not, it names every
field that disagrees plus the registered command that re-binds the case,
rather than refusing as one undifferentiated sentence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


#: The plan-bound environment snapshot (``qa_plans.target_environment_id``).
ENVIRONMENT_TARGET_SCHEMA = 2
#: The environmentless project snapshot for command and command-ci cases.
PROJECT_TARGET_SCHEMA = 3
#: The deployment snapshot resolved from a run's observed stage receipt.
DEPLOYMENT_TARGET_SCHEMA = 4
#: The shapes a Test Machine can execute. A project target is deliberately
#: absent: its cases run through command runners, never a host contract.
MACHINE_EXECUTABLE_TARGET_SCHEMAS = (
    ENVIRONMENT_TARGET_SCHEMA,
    DEPLOYMENT_TARGET_SCHEMA,
)
#: Identity a target may record about its environment. An environment
#: snapshot carries the name alone; a deployment snapshot also records the
#: registered environment row it resolved and which kind of destination it
#: is, and both are part of the digest the runner honours.
ENVIRONMENT_IDENTITY_KEYS = frozenset({"name", "id", "kind"})


class MachineQaCaseTargetError(ValueError):
    """A case's stored execution target cannot authorize machine execution."""


def case_target_mismatches(
    target: Mapping[str, Any],
    *,
    project_id: int,
    project: str,
) -> list[str]:
    """Name every field on which *target* disagrees with the case authority."""
    problems: list[str] = []
    schema = target.get("schema")
    if schema not in MACHINE_EXECUTABLE_TARGET_SCHEMAS:
        problems.append(
            f"schema: target declares {schema!r}; a Test Machine executes only "
            f"an environment target (schema {ENVIRONMENT_TARGET_SCHEMA}) or a "
            f"deployment target (schema {DEPLOYMENT_TARGET_SCHEMA})"
        )
    identity = target.get("project")
    if not isinstance(identity, Mapping):
        problems.append(
            "project: target records no project identity, while the case is "
            f"authored under {project!r} (id {project_id})"
        )
    else:
        if int(identity.get("id") or 0) != int(project_id):
            problems.append(
                f"project.id: target names {identity.get('id')!r}, case "
                f"authority names {int(project_id)}"
            )
        if str(identity.get("slug") or "") != str(project):
            problems.append(
                f"project.slug: target names {identity.get('slug')!r}, case "
                f"authority names {str(project)!r}"
            )
    environment = target.get("environment")
    if not isinstance(environment, Mapping):
        problems.append("environment: target records no environment identity")
    else:
        if not str(environment.get("name") or "").strip():
            problems.append("environment.name: target names no environment")
        unregistered = sorted(set(map(str, environment)) - ENVIRONMENT_IDENTITY_KEYS)
        if unregistered:
            problems.append(
                f"environment: target carries unregistered identity keys "
                f"{unregistered}; registered keys are "
                f"{sorted(ENVIRONMENT_IDENTITY_KEYS)}"
            )
    tenant = target.get("tenant")
    if not isinstance(tenant, Mapping) or not str(tenant.get("slug") or "").strip():
        problems.append("tenant.slug: target records no tenant identity")
    if not isinstance(target.get("endpoints"), Mapping):
        problems.append("endpoints: target declares no endpoint map to observe")
    return problems


def case_target_recovery(
    *,
    project: str,
    plan_id: int | None,
    deployment_run_id: str | None,
    deployment_stage: str | None = None,
    deployment_member: str | None = None,
    workflow_transition_id: str | None = None,
) -> str:
    """Name the registered command that re-binds this case to a live target.

    A deployment stage credits only requirements carrying its own stage name,
    and its member item when the stage is item-scoped, so the recovery names
    both rather than the run-wide form the stage would ignore.
    """
    if deployment_run_id:
        plan = str(plan_id) if plan_id is not None else "<plan>"
        stage = str(deployment_stage or "<stage>")
        member = f" --member {deployment_member}" if deployment_member else ""
        return (
            "Recovery: a deployment stage binds the run's own observed target, "
            "so re-materialize this case against it with `yoke qa plan "
            f"materialize --deployment-run-id {deployment_run_id} --stage "
            f"{stage}{member} --plan {plan} --project {project}`, then re-run "
            "the stage's cases. When the run itself has moved on, the evidence "
            "belongs to a replacement run rather than to this one."
        )
    if plan_id is None:
        return (
            "Recovery: re-bind the case's own environment with `yoke qa "
            "requirement update` and name an environment this project has "
            "registered."
        )
    transition = str(workflow_transition_id or "<transition>")
    return (
        "Recovery: bind the plan's target environment with `yoke qa plan edit "
        f"--plan {plan_id}`, then re-stamp the case with `yoke qa plan "
        f"rematerialize --item PREFIX-N --transition {transition}`."
    )


def require_case_execution_target(case: Any) -> None:
    """Refuse machine execution when the target is not the case's own.

    *case* is one ``MachineQaCaseContract``, taken as an untyped object
    because that model imports this check and naming its type here would
    close the cycle.
    """
    problems = case_target_mismatches(
        case.execution_target,
        project_id=case.project_id,
        project=case.project,
    )
    if not problems:
        return
    raise MachineQaCaseTargetError(
        "Machine QA execution target does not match its case authority "
        f"(QA requirement {case.requirement_id}): "
        + "; ".join(problems)
        + ". "
        + case_target_recovery(
            project=case.project,
            plan_id=case.plan_id,
            deployment_run_id=case.deployment_run_id,
            deployment_stage=case.deployment_stage,
            deployment_member=case.deployment_member_item_id,
            workflow_transition_id=case.workflow_transition_id,
        )
    )


__all__ = [
    "DEPLOYMENT_TARGET_SCHEMA",
    "ENVIRONMENT_IDENTITY_KEYS",
    "ENVIRONMENT_TARGET_SCHEMA",
    "MACHINE_EXECUTABLE_TARGET_SCHEMAS",
    "MachineQaCaseTargetError",
    "PROJECT_TARGET_SCHEMA",
    "case_target_mismatches",
    "case_target_recovery",
    "require_case_execution_target",
]
