"""The live session roster for the projects one caller can see.

Named-project refs resolve against that visibility, and the roster read
covers the whole resolved set in one pass: it is the same question for
every project it answers for, so running the pipeline once per project
would re-ask every enrichment the answer shares.

A session the caller may see can still hold work in a project the caller
may not: :func:`redact_hidden_projects` strips those claims, holdings and
the current item from each row before it leaves the server.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from yoke_contracts.api.function_call import FunctionCallRequest


def resolve_project_ids(
    conn: Any, project_refs: Sequence[str], visible: Optional[set[int]]
) -> Optional[set[int]]:
    """Named refs resolved against visibility, or ``visible`` unscoped when
    none are named. An unresolvable ref yields the empty set (matches
    nothing) rather than silently widening back to every visible project."""
    from yoke_core.domain.project_identity import resolve_project

    if not project_refs:
        return visible
    project_ids: set[int] = set()
    for project in project_refs:
        ident = resolve_project(
            conn, project, required=False, visible_project_ids=visible
        )
        if ident is None:
            return set()
        project_ids.add(ident.id)
    return project_ids


def org_session_clause(
    conn: Any, actor_id: int | None, permission_key: str | None = None
) -> tuple[str, list[Any]]:
    """SQL visibility matching the canonical org session read permission.

    The permission is decided once per organization the actor belongs to, so
    the cost never grows with the number of outside-project sessions.
    """
    from yoke_core.domain.actor_permissions import PERM_ITEMS_READ
    from yoke_core.domain.project_identity import placeholder
    from yoke_core.domain.session_scope_identity import org_ids_with_permission

    if actor_id is None:
        return "1 = 0", []
    marker = placeholder(conn)
    orgs = org_ids_with_permission(conn, actor_id, permission_key or PERM_ITEMS_READ)
    allowed = f"s.actor_id={marker}"
    if orgs:
        allowed += f" OR s.org_id IN ({', '.join(marker for _ in orgs)})"
    return f"(s.project_id IS NULL AND s.org_id IS NOT NULL AND ({allowed}))", [
        actor_id,
        *orgs,
    ]


#: Row fields that describe the session's current item.
_CURRENT_ITEM_FIELDS = (
    "current_item",
    "current_item_project_id",
    "current_item_project_sequence",
    "current_item_title",
    "current_item_status",
    "current_item_blocked_reason",
    "current_item_workflow_id",
    "current_item_workflow_version_id",
    "claim_started_at",
    "current_item_held_by_other_session_id",
    "work_role",
)


def _hidden(entry: Dict[str, Any], visible: set[int]) -> bool:
    """Whether a claim or holding names a project outside ``visible``."""
    for key in ("project_id", "item_project_id"):
        value = entry.get(key)
        if value is not None:
            return int(value) not in visible
    return False


def _visible_entries(entries: Any, visible: set[int]) -> Any:
    if not isinstance(entries, list):
        return entries
    return [e for e in entries if not (isinstance(e, dict) and _hidden(e, visible))]


def redact_hidden_projects(
    rows: List[Dict[str, Any]], visible: Optional[set[int]]
) -> List[Dict[str, Any]]:
    """Drop every claim, holding and current item from a hidden project.

    ``visible`` is ``None`` for local and admin-unscoped reads, which keep
    rows whole. The rows themselves stay: which sessions a caller sees is
    decided by the roster query, not here.
    """
    if visible is None:
        return rows
    for row in rows:
        row["claims"] = _visible_entries(row.get("claims") or [], visible)
        holdings = row.get("holdings")
        if isinstance(holdings, dict):
            removed_steering = any(
                isinstance(e, dict)
                and _hidden(e, visible)
                and e.get("target_kind") == "steering"
                for key in ("current", "previous")
                for e in holdings.get(key) or []
            )
            for key in ("current", "previous"):
                holdings[key] = _visible_entries(holdings.get(key), visible)
            if removed_steering:
                holdings["steered"] = any(
                    e.get("target_kind") == "steering"
                    for key in ("current", "previous")
                    for e in holdings.get(key) or []
                )
        if "holds" in row:
            row["holds"] = _visible_entries(row["holds"], visible)
        for owner in (row, row.get("session_state")):
            custody = owner.get("custody") if isinstance(owner, dict) else None
            if isinstance(custody, dict):
                custody["holds"] = _visible_entries(custody.get("holds"), visible)
        item_project = row.get("current_item_project_id")
        if item_project is not None and int(item_project) not in visible:
            row.update({field: None for field in _CURRENT_ITEM_FIELDS})
            row.update(
                current_item_frozen=False,
                current_item_blocked=False,
                owns_current_item=False,
            )
    return rows


def _matched_projects(row: Dict[str, Any]) -> set[int]:
    """The projects a roster row belongs to: its own, plus every project it
    holds a live steering claim over. Both facts are already on the row, so
    grouping the roster by project costs no further read."""
    matched: set[int] = set()
    if row.get("project_id") is not None:
        matched.add(int(row["project_id"]))
    for claim in row.get("claims") or []:
        if claim.get("target_kind") != "steering":
            continue
        claim_project = claim.get("project_id")
        if claim_project is not None:
            matched.add(int(claim_project))
    return matched


def open_roster_rows(
    request: FunctionCallRequest,
    project_refs: List[str],
    limit: int | None,
    offset: int = 0,
    **state_filters,
) -> List[Dict[str, Any]]:
    """The live roster for every project this caller can see, grouped by
    project in id order, each session appearing once."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.actor_project_visibility import (
        actor_visible_project_ids,
        numeric_actor_id,
    )
    from yoke_core.domain.sessions_list_read import list_sessions

    conn = db_helpers.connect()
    try:
        actor = request.actor.actor_id if request.actor else None
        visible = actor_visible_project_ids(conn, numeric_actor_id(actor))
        project_ids = resolve_project_ids(conn, project_refs, visible)
    finally:
        conn.close()
    org_actor = numeric_actor_id(actor) if not project_refs else None
    if project_ids is None:
        return redact_hidden_projects(
            list_sessions(
                open=True,
                limit=limit,
                offset=offset,
                org_session_actor_id=org_actor,
                **state_filters,
            ),
            visible,
        )
    if not project_ids and org_actor is None:
        # No visible project matches nothing, not everything: an unfiltered
        # read here would show the whole universe to a caller who can see
        # none of it.
        return []
    ordered = sorted(project_ids)
    # One roster read covers the whole visible set. Asking it once per project
    # re-ran the entire pipeline — the same whole-table claim-holder read, the
    # same page enrichments — for every project the operator can see.
    rows = list_sessions(
        project_ids=ordered,
        open=True,
        limit=limit,
        offset=offset,
        org_session_actor_id=org_actor,
        **state_filters,
    )
    # A session's live steering claim can name a project other than its own
    # home project, so the same session legitimately belongs to more than one
    # project's group; keep its first appearance and drop the repeat rather
    # than showing one session twice in the roster.
    by_session_id: Dict[str, Dict[str, Any]] = {}
    for project_id in ordered:
        for row in rows:
            if project_id in _matched_projects(row):
                by_session_id.setdefault(str(row.get("session_id") or ""), row)
    # A row the filter matched through a claim this projection does not carry
    # still belongs in the roster; it follows the grouped rows rather than
    # disappearing from the page.
    for row in rows:
        by_session_id.setdefault(str(row.get("session_id") or ""), row)
    return redact_hidden_projects(list(by_session_id.values()), visible)


def listed_roster_rows(
    request: FunctionCallRequest,
    project: Optional[str],
    **list_kwargs: Any,
) -> List[Dict[str, Any]]:
    """The non-open ``sessions.list`` read, cut to the caller's projects."""
    from yoke_core.domain import db_helpers
    from yoke_core.domain.actor_project_visibility import (
        actor_visible_project_ids,
        numeric_actor_id,
    )
    from yoke_core.domain.sessions_list_read import list_sessions

    actor = numeric_actor_id(request.actor.actor_id if request.actor else None)
    with db_helpers.connect() as conn:
        visible = actor_visible_project_ids(conn, actor)
    rows = list_sessions(
        project_ids=sorted(visible) if visible is not None else None,
        org_session_actor_id=actor if not project else None,
        project=project,
        **list_kwargs,
    )
    return redact_hidden_projects(rows, visible)


__all__ = [
    "listed_roster_rows",
    "open_roster_rows",
    "redact_hidden_projects",
    "resolve_project_ids",
]
