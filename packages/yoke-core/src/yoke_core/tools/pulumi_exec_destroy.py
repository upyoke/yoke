"""Operator-confirmed destruction and removal of one exact declared stack.

``destroy`` tears down a stack's resources; ``stack rm`` then removes the
emptied stack and its Yoke operator state.  Both need the outer
``--confirm-destroy <exact stack name>``; ``stack rm`` never takes
``--force``, so Pulumi itself refuses a stack that still holds resources.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    _first_mapping,
)
from yoke_core.domain.pulumi_state_capability import (
    CAPABILITY_TYPE as PULUMI_STATE_CAPABILITY_TYPE,
    validate_stack_state,
)
from yoke_core.tools.pulumi_exec_types import PulumiExecError


DESTROY = "destroy"
STACK_RM = "stack rm"
_DESTROY_FLAGS = frozenset(
    {"--yes", "--non-interactive", "--refresh", "--diff", "--suppress-outputs"}
)


def validated_destroy_argv(stack: str, args: Sequence[str]) -> list[str]:
    """Return the exact destroy argv for stack-flag-free ``args``."""
    for value in args:
        if value.startswith("--target"):
            raise PulumiExecError(
                "pulumi_destroy_target_refused: pulumi destroy runs on the "
                "whole stack and never takes --target; drop --target"
            )
        if value not in _DESTROY_FLAGS:
            raise PulumiExecError(
                f"Pulumi argument is not allowed for this operation: {value}"
            )
    if "--yes" not in args or "--non-interactive" not in args:
        raise PulumiExecError(
            "pulumi destroy requires --yes and --non-interactive"
        )
    return ["pulumi", "destroy", *args, "--stack", stack]


def validated_stack_rm_argv(stack: str, args: Sequence[str]) -> list[str]:
    """Return the exact ``stack rm`` argv for args following ``rm``."""
    for value in args:
        if value == "--force" or value.startswith("--force=") or value == "-f":
            raise PulumiExecError(
                "pulumi_stack_rm_force_refused: pulumi stack rm never takes "
                "--force, so Pulumi refuses a stack that still holds "
                "resources; run `destroy` on the stack first"
            )
    if list(args) != ["--yes"]:
        raise PulumiExecError(
            "Pulumi exec stack removal requires exactly `stack rm --yes`"
        )
    return ["pulumi", "stack", "rm", "--yes", "--stack", stack]


def destructive_operation(argv: Sequence[str]) -> str | None:
    """Name the destructive operation a validated argv runs, if any."""
    if argv[1:2] == [DESTROY]:
        return DESTROY
    if argv[1:3] == ["stack", "rm"]:
        return STACK_RM
    return None


def require_destroy_confirmation(
    stack: str, operation: str | None, confirm_destroy: str | None
) -> None:
    """Refuse unless ``--confirm-destroy`` names exactly the requested stack."""
    if operation is None:
        if confirm_destroy is not None:
            raise PulumiExecError(
                "pulumi_destroy_confirmation_unused: --confirm-destroy applies "
                "only to destroy and stack rm; drop it for this operation"
            )
        return
    if confirm_destroy is None:
        raise PulumiExecError(
            f"pulumi_destroy_confirmation_missing: pulumi {operation} requires "
            f"--confirm-destroy {stack}; rerun naming the exact stack"
        )
    if confirm_destroy != stack:
        raise PulumiExecError(
            "pulumi_destroy_confirmation_mismatch: --confirm-destroy names "
            f"{confirm_destroy!r} but the requested stack is {stack!r}; "
            "rerun naming the exact stack"
        )


def refuse_consumed_vps_stack(
    project: str, stack: str, settings: ProjectRendererSettings
) -> None:
    """Refuse while an environment stack with operator state uses ``stack``.

    An environment stack (one with its own ``pulumi.stack_name``) reads its
    origin from the VPS stack named by ``pulumi.origin_vps_stack_name``.
    Standalone VPS stacks are declared through that same key, so only a
    consumer that still has operator state blocks; it is destroyed first.
    """
    if settings.project != project:
        raise PulumiExecError(
            "Pulumi renderer settings do not match the requested project"
        )
    state_settings = settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE, {})
    try:
        operator_state = validate_stack_state(state_settings.get("stack_state", {}))
    except ValueError as exc:
        raise PulumiExecError("stored Pulumi operator state is invalid") from exc
    for environment in settings.environments:
        pulumi = _first_mapping(environment.settings.get("pulumi"))
        consumer = str(pulumi.get("stack_name") or "").strip()
        origin = str(pulumi.get("origin_vps_stack_name") or "").strip()
        if not consumer or consumer == stack or origin != stack:
            continue
        legacy_state = str(pulumi.get("encrypted_key") or "").strip()
        if consumer not in operator_state and not legacy_state:
            continue
        raise PulumiExecError(
            f"pulumi_stack_consumed: environment {environment.name!r} stack "
            f"{consumer!r} reads VPS stack {stack!r} as its origin and still "
            f"has operator state; destroy and remove {consumer!r} first with "
            f"`yoke pulumi exec --project {project} --stack {consumer} "
            f"--confirm-destroy {consumer} -- destroy --yes --non-interactive` "
            "and then `-- stack rm --yes`"
        )


def clear_removed_stack_state(
    project: str,
    stack: str,
    remover: Callable[..., Mapping[str, Any]],
    out: TextIO,
) -> None:
    """Drop operator state after ``pulumi stack rm`` exited 0."""
    try:
        receipt = dict(remover(project=project, stack_name=stack))
    except Exception as exc:
        raise PulumiExecError(
            f"Pulumi stack {stack!r} was removed but its operator state could "
            f"not be cleared ({exc}); stack init refuses that name until "
            "the pulumi-state capability's stack_state entry is removed"
        ) from exc
    out.write(
        f"Pulumi stack removed and operator state {receipt.get('mode')}: "
        f"{project}|{stack}|{receipt.get('receipt_digest')}\n"
    )
    out.flush()


__all__ = [
    "DESTROY",
    "STACK_RM",
    "clear_removed_stack_state",
    "destructive_operation",
    "refuse_consumed_vps_stack",
    "require_destroy_confirmation",
    "validated_destroy_argv",
    "validated_stack_rm_argv",
]
