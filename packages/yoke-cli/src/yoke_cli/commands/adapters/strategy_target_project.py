"""Project-aware destination resolution for strategy render writes.

``target_root`` resolution for ``yoke strategy render`` / ``doc replace``
/ ``doc archive`` / ``doc unarchive`` / ``ingest`` previously ignored the
selected project entirely: an explicit ``--target-root``/env override was
used as-is, and the implicit fallback was always the caller's cwd/repo
root (:func:`yoke_contracts.project_contract.workspace_roots.resolve_target_root_for_cli`).
A render or write-back for one project could therefore silently land
inside a DIFFERENT project's checkout whenever both projects happened to
share the operator's cwd and neither passed ``--target-root`` — e.g. a
``--project platform`` render issued from the Yoke checkout overwriting
Yoke's own ``.yoke/strategy/`` files with Platform's rendered docs.

These helpers add the missing project check ON TOP OF that unchanged
anchor resolution, once the operation's canonical ``project_id`` /
``project_slug`` are known (every ``strategy.*`` response carries them):
prefer this machine's own registered checkout for the project over an
unrelated cwd fallback, and refuse to write into an explicit or
fallback destination that machine config maps to a DIFFERENT project.
An unregistered destination is left alone either way, so an ad hoc
export or content-handoff path keeps working unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class StrategyTargetRootMismatchError(RuntimeError):
    """``target_root`` is this machine's registered checkout for another project."""


def target_root_was_explicit(arg_value: Optional[str]) -> bool:
    """Whether ``target_root`` resolution used an explicit override.

    Mirrors :func:`resolve_target_root_for_cli`'s own arg-then-env
    precedence, so callers can tell an operator-named destination
    (validate, never redirect) from an implicit cwd/worktree-guard
    fallback (prefer this machine's own project mapping first).
    """
    import os

    from yoke_contracts.project_contract.workspace_roots import (
        RENDER_TARGET_ROOT_ENV_VAR,
    )

    if arg_value:
        return True
    return bool(os.environ.get(RENDER_TARGET_ROOT_ENV_VAR, "").strip())


def mapped_checkout_for_project(project_id: int) -> Optional[Path]:
    """This machine's own registered checkout for ``project_id``, if any.

    The first existing-directory match wins when more than one checkout
    is mapped to the same project on this machine.
    """
    from yoke_cli.config import machine_config

    for configured in machine_config.configured_projects():
        if configured.project_id == project_id and configured.checkout.is_dir():
            return configured.checkout
    return None


def reject_target_root_project_mismatch(
    target_root: Path,
    *,
    project_id: int,
    project_slug: str,
) -> None:
    """Refuse ``target_root`` when it is registered to a DIFFERENT project.

    A path this machine has never registered to any project is left
    alone — an ad hoc export or content-handoff destination stays
    possible. Only a checkout registered to a project OTHER than the one
    that just served the read/write is refused.
    """
    from yoke_cli.config import machine_config

    mapped_id = machine_config.project_id(target_root)
    if mapped_id is not None and mapped_id != project_id:
        raise StrategyTargetRootMismatchError(
            f"{target_root} is this machine's registered checkout for "
            f"project {mapped_id}, not {project_slug!r} (project "
            f"{project_id}) — refusing to write {project_slug}'s "
            "strategy docs there. Pass an explicit --target-root naming "
            f"{project_slug}'s own checkout, or fix the mapping with "
            f"`yoke project register <correct checkout> --project-id "
            f"{project_id}`."
        )


def reject_known_target_root_mismatch(
    target_root: Path, *, project_id: Optional[object], project_slug: Optional[object],
) -> None:
    """Refuse ``target_root`` only when it's KNOWN to name a different project.

    Unlike :func:`resolve_and_validate_target_root`, this never redirects
    — it validates a source location the caller already resolved
    (explicit or cwd-derived) in place, since redirecting could move a
    READ away from wherever the operator's own edits actually live (a
    write destination has no such constraint). ``None`` identity fields
    (no project resolved yet) leave ``target_root`` alone.
    """
    if project_id is None or project_slug is None:
        return
    reject_target_root_project_mismatch(
        target_root, project_id=int(project_id), project_slug=str(project_slug),
    )


def resolve_implicit_target_root(
    fallback: Path,
    *,
    project_id: int,
    project_slug: str,
) -> Path:
    """Prefer the project's own machine mapping over an unrelated ``fallback``.

    ``fallback`` is the caller's already-resolved cwd/env anchor
    (:func:`resolve_target_root_for_cli`), used only when this project has
    no registered checkout on this machine. The fallback is itself
    validated: a cwd that happens to be registered to a DIFFERENT
    project is refused rather than silently written to.
    """
    mapped = mapped_checkout_for_project(project_id)
    if mapped is not None:
        return mapped
    reject_target_root_project_mismatch(
        fallback,
        project_id=project_id,
        project_slug=project_slug,
    )
    return fallback


def resolve_and_validate_target_root(
    resolved_target_root: Path,
    *,
    explicit: bool,
    project_id: Optional[object],
    project_slug: Optional[object],
) -> Path:
    """Apply the project check to an already Phase-1-resolved ``target_root``.

    ``project_id``/``project_slug`` come straight off a ``strategy.*``
    response's ``.get(...)`` — ``None`` when the response shape does not
    carry them (a stub in a narrower test, or a future degraded
    response), in which case resolution is left exactly as Phase 1 found
    it rather than guessing. Otherwise: an explicit destination is
    validated in place; an implicit one prefers the project's own
    machine mapping.
    """
    if project_id is None or project_slug is None:
        return resolved_target_root
    if explicit:
        reject_target_root_project_mismatch(
            resolved_target_root,
            project_id=int(project_id),
            project_slug=str(project_slug),
        )
        return resolved_target_root
    return resolve_implicit_target_root(
        resolved_target_root,
        project_id=int(project_id),
        project_slug=str(project_slug),
    )


__all__ = [
    "StrategyTargetRootMismatchError",
    "mapped_checkout_for_project",
    "reject_known_target_root_mismatch",
    "reject_target_root_project_mismatch",
    "resolve_and_validate_target_root",
    "resolve_implicit_target_root",
    "target_root_was_explicit",
]
