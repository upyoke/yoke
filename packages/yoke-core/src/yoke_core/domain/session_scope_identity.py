"""Exclusive session ownership and shared authorization for project or org scope."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain import actor_permission_checks, db_backend, db_helpers
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_lifecycle_identity import resolve_session_project_id
from yoke_core.hooks.relayed_session_identity import session_ownership_refusal


@dataclass(frozen=True)
class SessionScope:
    project_id: int | None
    org_id: int | None

    def __post_init__(self) -> None:
        if (self.project_id is None) == (self.org_id is None):
            raise SessionError(
                "SESSION_SCOPE_AMBIGUOUS",
                "A session requires exactly one project or organization scope. "
                "Recovery: open a new session in a registered project folder or request machine scope.",
            )

    @property
    def kind(self) -> str:
        return "project" if self.project_id is not None else "org"


def session_scope_of(row: Mapping[str, Any]) -> SessionScope:
    values = dict(row)
    return SessionScope(values.get("project_id"), values.get("org_id"))


def _member(conn: Any, actor_id: int, org_id: int) -> bool:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return (
        conn.execute(
            f"SELECT 1 FROM actor_org_roles WHERE actor_id = {marker} "
            f"AND org_id = {marker} LIMIT 1",
            (actor_id, org_id),
        ).fetchone()
        is not None
    )


def resolve_registration_scope(
    conn: Any, *, actor_id: int, project_id: int | None, machine_scope: bool
) -> SessionScope:
    if (project_id is not None) == bool(machine_scope):
        raise SessionError(
            "SESSION_SCOPE_AMBIGUOUS",
            "Choose a project or machine scope, exclusively. Recovery: open a new "
            "session in a registered project folder or request machine scope.",
        )
    if project_id is not None:
        return SessionScope(resolve_session_project_id(conn, project_id), None)
    try:
        org_id = default_org_id(conn)
    except Exception as exc:
        raise SessionError(
            "SESSION_ORG_UNRESOLVED",
            "The authority could not resolve this session's organization. Recovery: "
            "reconnect with `yoke connection set` or ask an org admin for membership.",
        ) from exc
    if not _member(conn, actor_id, org_id):
        raise SessionError(
            "SESSION_ORG_MEMBERSHIP_REQUIRED",
            "Session registration requires membership in this authority's organization. "
            "Recovery: reconnect with `yoke connection set` or ask an org admin for membership.",
        )
    return SessionScope(None, org_id)


def actor_may_operate_session(
    conn: Any,
    *,
    actor_id: int,
    scope: SessionScope,
    session_actor_id: int | None,
    permission_key: str,
) -> bool:
    if scope.project_id is not None:
        return actor_permission_checks.permission_decision(
            conn,
            actor_id=actor_id,
            project_id=scope.project_id,
            permission_key=permission_key,
        ).allowed
    if not _member(conn, actor_id, scope.org_id):
        return False
    return (
        actor_id == session_actor_id
        or actor_permission_checks.org_permission_decision(
            conn,
            actor_id=actor_id,
            org_id=scope.org_id,
            permission_key=permission_key,
        ).allowed
    )


def relay_serves_scope(
    *,
    relay_machine_id: str,
    relay_actor_id: int | None,
    advertised_project_ids: Collection[int],
    row_machine_id: str | None,
    row_project_id: int | None,
    row_org_id: int | None,
    row_actor_id: int | None,
) -> bool:
    if (row_project_id is None) == (row_org_id is None):
        return False
    if row_project_id is not None:
        return row_project_id in advertised_project_ids
    return (
        row_machine_id == relay_machine_id
        and relay_actor_id is not None
        and relay_actor_id == row_actor_id
    )


@dataclass(frozen=True)
class HookScopeDecision:
    project_slug: str = ""
    denial_code: str | None = None
    reason: str = ""


def authorize_hook_request(
    actor_id: int | None, project_id: int | None, session_ids: Collection[str]
) -> HookScopeDecision:
    try:
        with db_helpers.connect() as conn:
            if project_id is not None:
                visible = actor_visible_project_ids(conn, actor_id) or set()
                if project_id in visible:
                    slug = resolve_project_slug(conn, project_id)
                    if slug:
                        return HookScopeDecision(project_slug=slug)
                return HookScopeDecision(
                    denial_code="HOOK_PROJECT_DENIED",
                    reason="Hook project access denied. Recovery: use a connection with project membership.",
                )
            if actor_id is None:
                return HookScopeDecision(
                    denial_code="HOOK_SESSION_DENIED",
                    reason="Hook actor authentication is required. Recovery: reconnect with `yoke connection set`.",
                )
            for session_id in session_ids:
                if session_ownership_refusal(conn, session_id, actor_id):
                    return HookScopeDecision(
                        denial_code="HOOK_SESSION_DENIED",
                        reason="Hook session ownership denied. Recovery: relay through the connection whose actor owns the session.",
                    )
            return HookScopeDecision()
    except Exception:
        return HookScopeDecision(
            denial_code="HOOK_SCOPE_AUTH_UNAVAILABLE",
            reason="Hook scope authorization is unavailable. Recovery: restore the authority connection and retry.",
        )
