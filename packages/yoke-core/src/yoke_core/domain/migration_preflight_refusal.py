"""Why a release gate refuses, and the one command that clears it.

Split from :mod:`yoke_core.domain.migration_preflight_receipt` so the
coverage contract stays a contract: these functions author operator prose
and nothing here decides coverage. A refusal has one job — say which
environment is short which evidence, and name the command that produces it,
because a gate that only says no makes the operator go find out why.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from yoke_core.domain.migration_preflight_receipt import (
    target_environment_for_admin_env,
)

#: Project-generic unblock recipe. Callers that own a fleet adapter (for
#: example Yoke's release gate) inject that recipe via ``rehearse_command``;
#: the default must not name any project's source-dev path.
_DEFAULT_REHEARSE_COMMAND = (
    "yoke migration rehearse <item>  # see --help; use the project-owned "
    "fleet binding for fleet coverage before release"
)


def refusal_message(
    environment: str,
    missing: Sequence[str],
    *,
    product_sha: str = "",
    rehearse_command: str = "",
) -> str:
    """Why this release stops, and the one command that unblocks it.

    ``rehearse_command`` is the project-owned fleet recipe when a caller
    has one. Empty keeps the message project-generic so shared domain code
    never teaches a single project's source-dev adapter.
    """
    listed = ", ".join(missing)
    build = f" at {product_sha}" if product_sha.strip() else ""
    command = rehearse_command.strip() or _DEFAULT_REHEARSE_COMMAND
    return (
        f"this build{build} carries {len(missing)} migration history "
        f"entr{'y' if len(missing) == 1 else 'ies'} no passing fleet preflight "
        f"has covered for {target_environment_for_admin_env(environment)}: "
        f"{listed}. Receipts are per environment — a receipt for one is not "
        "coverage for another. An entry exists for the databases that are "
        "behind it, and nothing here has yet run it against one. Rehearse "
        f"the fleet, then re-run this release:\n  {command}"
    )


def schema_shape_refusal_message(
    environment: str,
    digest: str,
    *,
    product_sha: str = "",
    rehearse_command: str = "",
) -> str:
    """Why this release stops when the schema-shape digest is uncovered."""
    build = f" at {product_sha}" if product_sha.strip() else ""
    command = rehearse_command.strip() or _DEFAULT_REHEARSE_COMMAND
    return (
        f"this build{build} carries a schema-shape digest no passing fleet "
        f"preflight has covered for {target_environment_for_admin_env(environment)}: "
        f"{digest}. Additive schema converges on boot without a history entry, "
        "and CI only ever creates fresh databases, so an unrehearsed shape "
        "reaches the fleet as a missing column. Receipts are per environment. "
        f"Rehearse the fleet, then re-run this release:\n  {command}"
    )


def release_refusal_message(
    target_environment: str,
    missing_by_environment: Mapping[str, Sequence[str]],
    *,
    product_sha: str = "",
    rehearse_commands: Mapping[str, str] | None = None,
    engine_wheel_source: str = "",
) -> str:
    """Refuse, naming every environment still missing a receipt.

    The release still fails because *target_environment* is uncovered.
    Sibling environments are listed in the same message so the second gap
    is not discovered by a repeat attempt.
    """
    target = target_environment_for_admin_env(target_environment)
    commands = rehearse_commands or {}
    parts: list[str] = []
    target_missing = tuple(missing_by_environment.get(target) or ())
    parts.append(
        refusal_message(
            target,
            target_missing,
            product_sha=product_sha,
            rehearse_command=commands.get(target, ""),
        )
    )
    others = [
        (env, tuple(missing))
        for env, missing in missing_by_environment.items()
        if target_environment_for_admin_env(env) != target and missing
    ]
    if others:
        extra = "; ".join(f"{env}: {', '.join(missing)}" for env, missing in others)
        parts.append(
            "Also uncovered (receipts are per environment, so these are "
            f"separate gaps): {extra}."
        )
        for env, _missing in others:
            command = commands.get(env, "").strip()
            if command:
                parts.append(f"  {command}")
    covered = [
        env
        for env in missing_by_environment
        if target_environment_for_admin_env(env) != target
        and not missing_by_environment[env]
    ]
    if covered:
        named = ", ".join(target_environment_for_admin_env(env) for env in covered)
        parts.append(f"Covered for {named}; that evidence does not transfer.")
    if engine_wheel_source.strip():
        parts.append(engine_wheel_source.strip())
    return "\n".join(parts)


def unreadable_message(environment: str, reason: str) -> str:
    """Refuse when the coverage store could not be read at all.

    Distinguished from having found no receipt on purpose. Those are different
    facts — one says the release is unrehearsed, the other says this gate does
    not know — and reporting an unanswered question as a pass is the exact
    inversion that lets an unrehearsed build ship.
    """
    return (
        "could not read fleet preflight receipts for "
        f"{target_environment_for_admin_env(environment)}, so whether this "
        f"build was rehearsed is unknown rather than answered: {reason}. "
        "Refusing, because a gate that passes when it cannot check is not a "
        "gate. Coverage lives on that environment's own settings document, so "
        "a refused read usually means the identity running this gate lacks "
        "the project read that projection authorizes on; grant it that read "
        "on the project, then re-run."
    )
