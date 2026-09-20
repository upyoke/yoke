"""The live session roster for the projects one caller can see.

Named-project refs resolve against that visibility, and the roster read
covers the whole resolved set in one pass: it is the same question for
every project it answers for, so running the pipeline once per project
would re-ask every enrichment the answer shares.
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
    limit: int,
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
    if project_ids is None:
        return list_sessions(open=True, limit=limit)
    if not project_ids:
        # No visible project matches nothing, not everything: an unfiltered
        # read here would show the whole universe to a caller who can see
        # none of it.
        return []
    ordered = sorted(project_ids)
    # One roster read covers the whole visible set. Asking it once per project
    # re-ran the entire pipeline — the same whole-table claim-holder read, the
    # same page enrichments — for every project the operator can see.
    rows = list_sessions(project_ids=ordered, open=True, limit=limit)
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
    return list(by_session_id.values())


__all__ = ["open_roster_rows", "resolve_project_ids"]
