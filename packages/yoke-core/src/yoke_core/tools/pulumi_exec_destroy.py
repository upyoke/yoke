"""Operator-confirmed destruction and removal of one exact declared stack.

``destroy`` tears down a stack's resources; ``stack rm`` then removes the
emptied stack.  Mutating operations need the outer
``--confirm-destroy <exact stack name>``; ``stack rm`` never takes
``--force``, so Pulumi itself refuses a stack that still holds resources.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import yaml

from yoke_core.domain.pack_pulumi_sources import (
    PULUMI_PROGRAM_SUBDIRECTORY,
    pulumi_program_source,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    _first_mapping,
)
from yoke_core.tools.pulumi_exec_source import _git
from yoke_core.tools.pulumi_exec_types import PulumiExecError


DESTROY = "destroy"
STACK_RM = "stack rm"
_DESTROY_FLAGS = frozenset(
    {"--yes", "--non-interactive", "--refresh", "--diff", "--suppress-outputs",
     "--preview-only"}
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
    if "--preview-only" in args:
        if "--yes" in args or "--refresh" in args:
            raise PulumiExecError(
                "pulumi_destroy_preview_mutation_refused: destroy --preview-only "
                "never takes --yes or --refresh; drop them for a read-only preview"
            )
        return ["pulumi", "destroy", *args, "--stack", stack]
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
    project: str,
    stack: str,
    settings: ProjectRendererSettings,
    project_root: Path,
) -> str:
    """Refuse real StackReference consumers; explain selector-only uses.

    The guard reads committed consumer config only: it refuses outside a
    committed git checkout and refuses any uncommitted change to the files
    it reads, so the files on disk (which the Pulumi run also copies) are
    exactly the committed ones.
    """
    if settings.project != project:
        raise PulumiExecError(
            "Pulumi project settings do not match the requested project"
        )
    if not _git(project_root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"):
        raise PulumiExecError(
            f"pulumi_stack_consumer_uncommitted: {project_root} is not a git "
            "checkout with a commit, so the destroy guard cannot read committed "
            "consumer config; run from the project's committed checkout, commit "
            f"{PULUMI_PROGRAM_SUBDIRECTORY}/, then retry"
        )
    selectors = []
    for environment in settings.environments:
        pulumi = _first_mapping(environment.settings.get("pulumi"))
        consumer = str(pulumi.get("stack_name") or "").strip()
        origin = str(pulumi.get("origin_vps_stack_name") or "").strip()
        if not consumer or consumer == stack or origin != stack:
            continue
        consumer_file = pulumi_program_source(project_root, f"Pulumi.{consumer}.yaml")
        _require_committed(project_root, ("Pulumi.yaml", consumer_file.name))
        if not consumer_file.is_file():
            continue
        if _consumer_origin_ip(project_root, consumer_file):
            selectors.append(
                f"{stack!r} stays in use as the live selector for "
                f"environment {environment.name!r} stack {consumer!r}"
            )
            continue
        raise PulumiExecError(
            f"pulumi_stack_consumed: environment {environment.name!r} stack "
            f"{consumer!r} creates a StackReference to VPS stack {stack!r} "
            "because its origin_ip is empty; keep the VPS stack until the "
            "consumer no longer needs its outputs, then set origin_ip in its "
            "committed config and retry"
        )
    detail = "; ".join(selectors) or "no committed StackReference consumers"
    return f"pulumi_stack_destroy_allowed: {detail}"


def _require_committed(project_root: Path, filenames: Sequence[str]) -> None:
    """Refuse unless the named infra files match HEAD, untracked included.

    ``--branch`` always prints a ``##`` header on success, so an empty answer
    means git itself failed and the guard stays closed.
    """
    paths = [f"{PULUMI_PROGRAM_SUBDIRECTORY}/{name}" for name in filenames]
    status = _git(
        project_root, "status", "--porcelain", "--branch", "--ignored",
        "--untracked-files=all", "--", *paths,
    )
    lines = status.splitlines()
    if not lines or not lines[0].startswith("##"):
        raise PulumiExecError(
            f"pulumi_stack_consumer_uncommitted: git status failed for "
            f"{', '.join(paths)} in {project_root}; repair the checkout, then retry"
        )
    changed = [line[3:] for line in lines[1:] if line.strip()]
    if changed:
        raise PulumiExecError(
            f"pulumi_stack_consumer_uncommitted: {', '.join(changed)} differs "
            "from the committed checkout, so the destroy guard cannot trust it; "
            "commit or revert the change to the named file, then retry"
        )


def _consumer_origin_ip(project_root: Path, consumer_file: Path) -> str:
    """Read the consumer's explicit origin_ip under the declared namespace.

    An empty value means the consumer reads the VPS stack's outputs. A
    missing or non-string value refuses as invalid config, so the guard
    stays closed when the dependency cannot be read.
    """
    declaration_file = pulumi_program_source(project_root, "Pulumi.yaml")
    recovery = (
        f"pulumi_stack_consumer_config_invalid: cannot determine the "
        f"StackReference dependency from {consumer_file}; repair infra/Pulumi.yaml "
        "name and an explicit namespaced origin_ip (a string, empty when "
        "unset) in the consumer config, then retry"
    )
    try:
        declaration = yaml.safe_load(declaration_file.read_text(encoding="utf-8"))
        consumer = yaml.safe_load(consumer_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PulumiExecError(recovery) from exc
    namespace = declaration.get("name") if isinstance(declaration, dict) else None
    config = consumer.get("config") if isinstance(consumer, dict) else None
    if not isinstance(namespace, str) or not namespace.strip() or not isinstance(config, dict):
        raise PulumiExecError(recovery)
    origin_ip = config.get(f"{namespace}:origin_ip")
    if not isinstance(origin_ip, str):
        raise PulumiExecError(recovery)
    return origin_ip.strip()


__all__ = [
    "DESTROY",
    "STACK_RM",
    "destructive_operation",
    "refuse_consumed_vps_stack",
    "require_destroy_confirmation",
    "validated_destroy_argv",
    "validated_stack_rm_argv",
]
