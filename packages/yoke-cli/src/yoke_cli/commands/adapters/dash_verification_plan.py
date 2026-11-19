"""Project-scoped verification-plan resolution for Dash filing."""

from __future__ import annotations

from typing import Mapping

from yoke_cli.commands import _helpers
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.verification_posture import REGISTERED_COMMAND_PLAN_PREFIX

#: The plan a Dash filed without a verification choice is verified by: the
#: project's registered quick command. A project with no registered quick
#: command, or one that attested it has no suite (which retires the plan),
#: files with no verification.
PROJECT_DEFAULT_DASH_PLAN_SLUG = f"{REGISTERED_COMMAND_PLAN_PREFIX}quick"

#: ``--verification-method none`` files a Dash with no verification and
#: skips the project default.
NO_VERIFICATION_METHOD = "none"


class DashVerificationPlanError(ValueError):
    """A Dash verification-plan reference could not resolve safely."""


def _fetch_plan(
    reference: str, *, project: str, session_id: str | None
) -> Mapping | None:
    """Read one plan by slug; ``None`` when the project has no such plan."""
    _helpers.ensure_handlers_loaded()
    fetched = call_dispatcher(
        function_id="qa.plan.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "plan_id": reference},
        actor=build_actor(session_id=session_id),
    )
    if not fetched.success:
        error = fetched.error
        if error is not None and getattr(error, "code", None) == "not_found":
            return None
        detail = error.message if error is not None else "qa.plan.get failed"
        raise DashVerificationPlanError(
            f"could not resolve verification plan slug {reference!r} "
            f"in project {project!r}: {detail}"
        )
    plan = (fetched.result or {}).get("plan")
    if not isinstance(plan, Mapping):
        raise DashVerificationPlanError(
            f"qa.plan.get returned no plan document for slug {reference!r} "
            f"in project {project!r}"
        )
    return plan


def _plan_id(plan: Mapping, *, reference: str, project: str) -> int:
    try:
        return int(plan["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DashVerificationPlanError(
            f"verification plan slug {reference!r} in project {project!r} "
            "has no valid integer id"
        ) from exc


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

    plan = _fetch_plan(reference, project=project, session_id=session_id)
    if plan is None:
        raise DashVerificationPlanError(
            f"could not resolve verification plan slug {reference!r} "
            f"in project {project!r}: not found; list plans with "
            f"`yoke qa plan list --project {project}`"
        )
    if plan.get("retired_at") is not None:
        raise DashVerificationPlanError(
            f"verification plan slug {reference!r} in project {project!r} is "
            "retired; name an active plan from `yoke qa plan list --project P`"
        )
    return _plan_id(plan, reference=reference, project=project)


def project_default_dash_verification_plan(
    *, project: str | None, session_id: str | None
) -> int | None:
    """The project's active registered quick plan, or ``None`` without one.

    Without project context the create itself refuses naming the project, so
    there is no default to read here.
    """
    if project is None:
        return None
    reference = PROJECT_DEFAULT_DASH_PLAN_SLUG
    plan = _fetch_plan(reference, project=project, session_id=session_id)
    if plan is None or plan.get("retired_at") is not None:
        return None
    return _plan_id(plan, reference=reference, project=project)


__all__ = [
    "DashVerificationPlanError",
    "NO_VERIFICATION_METHOD",
    "PROJECT_DEFAULT_DASH_PLAN_SLUG",
    "project_default_dash_verification_plan",
    "resolve_dash_verification_plan",
]
