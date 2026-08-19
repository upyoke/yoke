"""Project-scoped verification-plan resolution for Dash filing."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_cli.commands import _helpers
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef


class DashVerificationPlanError(ValueError):
    """A Dash verification-plan reference could not resolve safely."""


def resolve_dash_verification_plan(
    reference: str,
    *,
    project: str | None,
    session_id: str | None,
) -> int:
    """Resolve an integer id directly or a slug within one project."""
    try:
        return int(reference)
    except ValueError:
        pass

    if project is None:
        raise DashVerificationPlanError(
            f"verification plan slug {reference!r} needs project context; "
            "pass --project P or run from a registered checkout"
        )

    _helpers.ensure_handlers_loaded()
    listed = call_dispatcher(
        function_id="qa.plan.list",
        target=TargetRef(kind="global"),
        payload={"project": project},
        actor=build_actor(session_id=session_id),
    )
    if not listed.success:
        detail = (
            listed.error.message if listed.error is not None else "qa.plan.list failed"
        )
        raise DashVerificationPlanError(
            f"could not resolve verification plan slug {reference!r} "
            f"in project {project!r}: {detail}"
        )

    rows = (listed.result or {}).get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise DashVerificationPlanError(
            f"qa.plan.list returned an invalid plan roster for project {project!r}"
        )

    matches = [row for row in rows if row.get("slug") == reference]
    if not matches:
        raise DashVerificationPlanError(
            f"verification plan slug {reference!r} was not found in project {project!r}"
        )
    if len(matches) > 1:
        raise DashVerificationPlanError(
            f"verification plan slug {reference!r} is ambiguous in project "
            f"{project!r}; candidates: {_candidate_list(matches)}"
        )

    try:
        return int(matches[0]["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DashVerificationPlanError(
            f"verification plan slug {reference!r} in project {project!r} "
            "has no valid integer id"
        ) from exc


def _candidate_list(rows: Sequence[Mapping[str, Any]]) -> str:
    """Render every ambiguous candidate without silently preferring one."""
    return ", ".join(f"id={row.get('id')!r} name={row.get('name')!r}" for row in rows)


__all__ = [
    "DashVerificationPlanError",
    "resolve_dash_verification_plan",
]
