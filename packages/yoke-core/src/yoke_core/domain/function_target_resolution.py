"""Resolve persisted target project/org authority for dispatched calls.

Payloads and target rows identify the concrete permission scope. An operation
without a resolvable project is denied rather than aimed at a default project.
"""

from __future__ import annotations

from typing import Any, Collection

from yoke_core.domain.function_org_context_resolution import resolve_org_context
from yoke_core.domain.function_project_selection import PAYLOAD_NAMED_PROJECT_FUNCTIONS
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
from yoke_core.domain.function_target_coordination_claim_project import (
    resolve_coordination_claim_project_context,
)
from yoke_core.domain.function_target_ouroboros_entry_project import (
    resolve_ouroboros_entry_context,
)
from yoke_core.domain.qa_deployment_function_subject import (
    SCOPED_RUN_FUNCTIONS,
    QaSubjectProjectError,
    resolve_run_qa_subject,
)
from yoke_core.domain.function_unresolved_project import (
    ProjectNotRegisteredError,
    control_plevel_label,
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
    from yoke_core.domain.qa_execution_request_identity import (
        is_execution_request,
        resolve_execution_request,
    )

    if is_execution_request(request):
        request = resolve_execution_request(conn, request)
    if entry.function_id == "claims.path.override":
        try:
            return resolve_path_claim_project(
                conn, int(request.payload["path_claim_id"])
            )
        except (KeyError, TypeError, ValueError):
            return None
    if request.target.kind == "item":
        item_id = request.target.item_id
        return resolve_item_project(conn, int(item_id)) if item_id is not None else None
    if entry.function_id == "ephemeral_env.update":
        try:
            env_id = int(request.payload.get("env_id"))
        except (TypeError, ValueError):
            return None
        return resolve_ephemeral_env_project(conn, env_id)
    if entry.function_id.startswith("github_actions."):
        return _resolve_github_actions_project_context(
            conn, request, visible_project_ids=visible_project_ids
        )
    if entry.function_id in PAYLOAD_NAMED_PROJECT_FUNCTIONS:
        return _resolve_named_project_context(
            conn, request, visible_project_ids=visible_project_ids
        )
    if entry.function_id.startswith("ouroboros.") and request.payload.get(
        "entry_id"
    ):
        return resolve_ouroboros_entry_context(
            conn,
            request,
            visible_project_ids=visible_project_ids,
        )
    if entry.function_id.startswith("claims.coordination_claim."):
        coordination_context = resolve_coordination_claim_project_context(
            conn,
            request,
            visible_project_ids=visible_project_ids,
        )
        if coordination_context is not None:
            return coordination_context
    if request.target.claim_id is not None:
        claim_context = resolve_work_claim_project(
            conn,
            int(request.target.claim_id),
            visible_project_ids=visible_project_ids,
        )
        if claim_context is not None:
            return claim_context
    path_claim_id = request.target.path_claim_id
    if path_claim_id is None:
        raw_claim = request.payload.get("path_claim_id")
        if raw_claim is not None:
            try:
                path_claim_id = int(raw_claim)
            except (TypeError, ValueError):
                path_claim_id = None
    if path_claim_id is not None:
        path_claim_context = resolve_path_claim_project(
            conn,
            int(path_claim_id),
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
    deployment_run_id = target.deployment_run_id or target.workflow_run_id
    if deployment_run_id is not None:
        if entry.function_id in SCOPED_RUN_FUNCTIONS:
            project_id, slug, _member_id = resolve_run_qa_subject(conn, request)
            return project_id, slug
        deployment_project = resolve_deployment_run_project(
            conn,
            str(deployment_run_id),
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
    if entry.function_id.startswith("qa.") and target.qa_requirement_id is not None:
        qa_project = resolve_qa_requirement_project(conn, int(target.qa_requirement_id))
        if qa_project is None:
            return None
        if target.project_id:
            try:
                hinted_id = resolve_project_id(conn, str(target.project_id))
            except LookupError as exc:
                raise QaSubjectProjectError(
                    f"QA project hint {target.project_id!r} was not found; "
                    f"use project {qa_project[1]!r}"
                ) from exc
            if hinted_id != qa_project[0]:
                raise QaSubjectProjectError(
                    f"QA project hint {target.project_id!r} does not match "
                    f"requirement project {qa_project[1]!r}; use that project"
                )
        return qa_project
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
    if entry.function_id in {"qa.method.list", "qa.method.get"}:
        return _qa_method_session_project(conn, request)
    # An unresolved target is denied upstream.
    return None


def _qa_method_session_project(
    conn: Any, request: FunctionCallRequest
) -> tuple[int, str] | None:
    """Permission scope for a method read that omitted --project.

    Reads only the stored session project. The full session identity also
    opens harness files, and this resolver runs inside server hook policy.
    A session with no project stays unresolved so the caller passes --project.
    """
    session_id = str(request.actor.session_id or "").strip()
    if not session_id:
        return None
    row = conn.execute(
        "SELECT project_id FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    project_id = int(row[0])
    return project_id, slug_for_project_id(conn, project_id)


def _resolve_github_actions_project_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve non-item GitHub Actions authority from its project payload."""
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
    except LookupError as exc:
        raise ProjectNotRegisteredError(
            payload_ref,
            plane=control_plevel_label(),
        ) from exc
    return project_id, slug_for_project_id(conn, project_id)


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
