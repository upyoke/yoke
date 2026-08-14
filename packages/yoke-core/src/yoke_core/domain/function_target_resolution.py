"""Resolve the target project / org for a dispatched function call.

Split from :mod:`yoke_core.domain.yoke_function_permissions` (which owns the
scope routing) to keep each module under the authored-file line cap. These
helpers turn a request's payload/target hints — and, when those are absent,
the target row's own project — into the concrete project or org the
permission check runs against. A project-scoped op that still cannot name
its target resolves to ``None`` and is denied upstream (never silently
aimed at the yoke project).
"""

from __future__ import annotations

from typing import Any, Collection

from yoke_core.domain.function_org_context_resolution import resolve_org_context
from yoke_core.domain.function_target_row_project import (
    resolve_authorized_project_id,
    resolve_deployment_run_project,
    resolve_ephemeral_env_project,
    resolve_item_project,
    resolve_ouroboros_entry_project,
    resolve_path_claim_project,
    resolve_qa_requirement_project,
    resolve_work_claim_project,
    slug_for_project_id,
)
from yoke_core.domain.project_identity import (
    AmbiguousProjectRefError,
    resolve_project_id,
)
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.yoke_function_registry import RegistryEntry


def resolve_project_context(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve the real target project for a PROJECT-scoped op (or None)."""
    if entry.function_id == "ephemeral_env.update":
        try:
            env_id = int(request.payload.get("env_id"))
        except (TypeError, ValueError):
            return None
        return resolve_ephemeral_env_project(conn, env_id)
    if entry.function_id.startswith("github_actions."):
        return _resolve_github_actions_project_context(
            conn,
            request,
            visible_project_ids=visible_project_ids,
        )
    if entry.function_id in _PAYLOAD_NAMED_PROJECT_FUNCTIONS:
        return _resolve_named_project_context(
            conn,
            request,
            visible_project_ids=visible_project_ids,
        )
    if entry.function_id.startswith("ouroboros.entry.") and request.payload.get(
        "entry_id"
    ):
        return _resolve_ouroboros_entry_context(
            conn,
            request,
            visible_project_ids=visible_project_ids,
        )
    if request.target.claim_id is not None:
        claim_context = resolve_work_claim_project(
            conn,
            int(request.target.claim_id),
            visible_project_ids=visible_project_ids,
        )
        if claim_context is not None:
            return claim_context
    if request.target.path_claim_id is not None:
        path_claim_context = resolve_path_claim_project(
            conn,
            int(request.target.path_claim_id),
        )
        if path_claim_context is not None:
            return path_claim_context
    process_context = _resolve_process_target_project_context(
        conn,
        request,
        visible_project_ids=visible_project_ids,
    )
    if process_context is not None:
        return process_context
    target = request.target
    if target.deployment_run_id is not None:
        deployment_project = resolve_deployment_run_project(
            conn,
            str(target.deployment_run_id),
        )
        if deployment_project is None:
            return None
        if target.project_id:
            try:
                hinted_project_id = resolve_authorized_project_id(
                    conn,
                    str(target.project_id),
                    visible_project_ids,
                )
            except (AmbiguousProjectRefError, LookupError):
                return None
            if hinted_project_id != deployment_project[0]:
                return None
        return deployment_project
    explicit = (
        target.project_id
        or request.payload.get("project_id")
        or request.payload.get("project")
    )
    if explicit:
        try:
            project_id = resolve_authorized_project_id(
                conn,
                str(explicit),
                visible_project_ids,
            )
        except AmbiguousProjectRefError:
            raise
        except LookupError:
            return None
        return project_id, slug_for_project_id(conn, project_id)
    item_id = target.item_id or target.epic_id
    if item_id is not None:
        item_project = resolve_item_project(conn, int(item_id))
        if item_project is not None:
            return item_project
    if target.qa_requirement_id is not None:
        qa_project = resolve_qa_requirement_project(
            conn,
            int(target.qa_requirement_id),
        )
        if qa_project is not None:
            return qa_project
    entry_id = request.payload.get("entry_id")
    if entry_id is not None:
        try:
            entry_project = resolve_ouroboros_entry_project(conn, int(entry_id))
        except (TypeError, ValueError):
            entry_project = None
        if entry_project is not None:
            return entry_project
    # No project hint or target-row project resolved. Authority is the actor's
    # identity, not a default project — a project-scoped op that cannot name
    # its target is denied upstream (no "fall back to yoke" guess).
    return None


# Functions whose target project lives in payload ``slug``, ``project``, or
# ``scope``; a target-ref hint must agree with that payload authority.
_PAYLOAD_NAMED_PROJECT_FUNCTIONS = frozenset(
    {
        "ephemeral_env.create",
        "ephemeral_env.get",
        "projects.update",
        "projects.capability_settings.get",
        "projects.capability_settings.set",
        "projects.capability_settings.merge",
        "projects.capability_settings.remove",
        "projects.environment_settings.get",
        "projects.environment_settings.merge",
        "projects.infrastructure.list",
        "packs.list",
        "packs.bundle.get",
        "packs.project.report",
        "projects.pulumi_state.migrate",
        "projects.pulumi_state.checkpoint_import",
        "projects.pulumi_stack_config.get",
        "board.data.get",
        "board.rebuild.run",
    }
)


def _resolve_github_actions_project_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve GitHub Actions authority from the handler's project payload.

    GitHub Actions handlers use ``payload.project`` to select both the GitHub
    App installation and repository binding. Authorization must therefore use
    that same project. A target hint is optional, but when supplied it must
    resolve to the identical project rather than selecting a different scope
    for the permission check.
    """
    payload_ref = str(request.payload.get("project") or "").strip()
    if not payload_ref:
        return None
    try:
        project_id = resolve_authorized_project_id(
            conn,
            payload_ref,
            visible_project_ids,
        )
        target_ref = str(request.target.project_id or "").strip()
        if target_ref and resolve_project_id(conn, target_ref) != project_id:
            return None
    except AmbiguousProjectRefError:
        raise
    except LookupError:
        return None
    return project_id, slug_for_project_id(conn, project_id)


def _resolve_ouroboros_entry_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve an entry-targeted Ouroboros op's project from the entry row.

    The row is the authority: a caller's project — ``--project``, or the
    ambient checkout the client CLI attaches — may confirm it but never
    redirect it, so an id from one project can't be written while authorized
    as another. Only an entry belonging to no project falls through to the
    caller's, since no row authority exists to prefer.
    """
    try:
        entry_id = int(request.payload["entry_id"])
    except (TypeError, ValueError):
        return None
    row_context = resolve_ouroboros_entry_project(conn, entry_id)
    hint = (
        request.target.project_id
        or request.payload.get("project_id")
        or request.payload.get("project")
    )
    if hint:
        try:
            hinted_id = resolve_authorized_project_id(
                conn,
                str(hint),
                visible_project_ids,
            )
        except AmbiguousProjectRefError:
            raise
        except LookupError:
            return None
        if row_context is not None and hinted_id != row_context[0]:
            return None
        if row_context is None:
            return hinted_id, slug_for_project_id(conn, hinted_id)
    return row_context


def _resolve_process_target_project_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve a process work-claim's target project from the payload target.

    A process work claim (``claims.work.acquire`` with a ``--process`` target)
    carries a ``kind='process'`` target spec in the payload whose ``project``
    names the per-project process authority — every process conflict group is
    per-project (e.g. ``strategy-control-plane:<project>``). The envelope
    ``TargetRef`` is ``kind='global'`` with no project id, so the project must
    be read from ``payload['target']['project']`` — the same field the acquire
    handler consumes. Returns ``None`` for any non-process target so the caller
    falls through to the remaining resolution branches.
    """
    payload_target = request.payload.get("target")
    if not isinstance(payload_target, dict) or payload_target.get("kind") != "process":
        return None
    ref = payload_target.get("project")
    if not ref:
        return None
    try:
        project_id = resolve_authorized_project_id(
            conn,
            str(ref),
            visible_project_ids,
        )
    except AmbiguousProjectRefError:
        raise
    except LookupError:
        return None
    return project_id, slug_for_project_id(conn, project_id)


def _resolve_named_project_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve a project op's target from a payload field that names the project.

    Covers ops that carry their target project in the payload rather than the
    target ref — ``projects.*`` by ``slug``/``project``, ``board.*`` by
    ``scope``. A target-ref project is only a consistency hint and must match.
    """
    ref = (
        request.payload.get("slug")
        or request.payload.get("scope")
        or request.payload.get("project")
        or request.payload.get("project_id")
    )
    if not ref:
        return None
    try:
        project_id = resolve_authorized_project_id(
            conn,
            str(ref),
            visible_project_ids,
        )
        target_ref = str(request.target.project_id or "").strip()
        if target_ref and resolve_project_id(conn, target_ref) != project_id:
            return None
    except AmbiguousProjectRefError:
        raise
    except LookupError:
        return None
    return project_id, slug_for_project_id(conn, project_id)


__all__ = [
    "resolve_project_context",
    "resolve_org_context",
]
