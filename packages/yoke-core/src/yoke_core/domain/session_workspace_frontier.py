"""Filter argless frontier assignment to the session's workspace project.

Argless ``/yoke do`` and ``/yoke charge`` still compute the all-projects
schedule so other projects remain visible, then keep only the invoking
workspace's project for claiming. An explicit ``--project`` or ``--item``
bypasses the filter. An unmapped folder assigns nothing and returns a
grouped elsewhere reply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_core.domain.scheduler_types import is_assignable_claim_state


def resolve_offer_home_project(
    conn: Any,
    *,
    workspace: str,
    session_id: Optional[str] = None,
) -> Optional[int]:
    """Resolve the workspace-home project id, or ``None`` when unmapped.

    Prefers the machine checkout mapping for *workspace*. A path that
    exists on this machine and is not mapped is unmapped (no silent
    yoke fallback). When the path is absent here — the hosted-server
    case — fall back to ``harness_sessions.project_id``, which begin
    already resolved on the client.
    """
    text = (workspace or "").strip()
    if text:
        mapped = _mapped_project_id(text)
        if mapped is not None:
            return mapped
        root = Path(text)
        if root.is_absolute() and root.exists():
            return None
    if session_id:
        return _session_project_id(conn, session_id)
    return None


def workspace_home_filter_requested(
    *,
    project_override: Optional[Any] = None,
    item: Optional[str] = None,
) -> bool:
    """True when argless charge/do should keep only the workspace-home project."""
    return project_override is None and not str(item or "").strip()


def apply_workspace_home_filter(
    schedule: Any,
    *,
    home_project_id: Optional[int],
    conn: Any = None,
) -> Any:
    """Keep home-project steps for assignment; stash the rest as elsewhere.

    ``home_project_id is None`` is the unmapped-folder case: nothing is
    assignable and every assignable ranked step becomes elsewhere.
    """
    ranked = list(getattr(schedule, "ranked_steps", []) or [])
    home_slug = _home_slug(conn, home_project_id)
    if home_project_id is None:
        home_steps: List[Any] = []
        elsewhere_steps = ranked
    else:
        home_steps = [step for step in ranked if _step_is_home(step, home_project_id, home_slug)]
        elsewhere_steps = [step for step in ranked if step not in home_steps]
    groups = group_runnable_elsewhere(elsewhere_steps, conn)
    assignable_home = [
        step for step in home_steps if is_assignable_claim_state(step.claim_state)
    ]
    schedule.ranked_steps = home_steps
    schedule.conduct_eligible = [
        step
        for step in list(getattr(schedule, "conduct_eligible", []) or [])
        if _step_is_home(step, home_project_id, home_slug)
    ] if home_project_id is not None else []
    schedule.selected_step = assignable_home[0] if assignable_home else None
    schedule.runnable_elsewhere = groups
    schedule.workspace_home_project = home_slug
    _append_workspace_home_diagnostic(
        schedule,
        before=len(ranked),
        eliminated=len(elsewhere_steps),
        home_slug=home_slug,
        eliminated_items=_step_refs(elsewhere_steps, conn),
    )
    return schedule


def group_runnable_elsewhere(steps: List[Any], conn: Any = None) -> List[Dict[str, Any]]:
    """Group assignable non-home steps by project for the operator reply."""
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id
    from yoke_core.domain.sessions_queries_base import display_claim_item_id

    buckets: Dict[str, List[str]] = {}
    for step in steps:
        if not is_assignable_claim_state(getattr(step, "claim_state", None)):
            continue
        slug = (getattr(step, "project", None) or "").strip() or "unknown"
        ref = display_claim_item_id(str(getattr(step, "item_id", "")), conn) or str(
            getattr(step, "item_id", "")
        )
        buckets.setdefault(slug, []).append(ref)
    groups: List[Dict[str, Any]] = []
    for slug in sorted(buckets):
        refs = buckets[slug]
        project_id = _project_id_for_slug(conn, slug)
        checkout = checkout_for_project_id(project_id) if project_id is not None else None
        groups.append(
            {
                "project": slug,
                "project_id": project_id,
                "count": len(refs),
                "public_refs": refs,
                "checkout_path": str(checkout) if checkout is not None else "",
            }
        )
    return groups


def build_runnable_elsewhere_context(
    *,
    groups: List[Dict[str, Any]],
    home_project: Optional[str],
    unmapped: bool,
) -> Dict[str, Any]:
    """WAIT context when assignment is empty but other projects have work."""
    return {
        "wait_reason": "runnable_elsewhere",
        "workspace_home_project": home_project,
        "workspace_unmapped": unmapped,
        "runnable_elsewhere": list(groups),
        "runnable_elsewhere_note": render_runnable_elsewhere_note(
            groups, home_project=home_project, unmapped=unmapped,
        ),
    }


def render_runnable_elsewhere_note(
    groups: List[Dict[str, Any]],
    *,
    home_project: Optional[str],
    unmapped: bool,
) -> str:
    """Refusal-teaches-recipe line naming counts, refs, and checkout paths."""
    parts = []
    for group in groups:
        checkout = group.get("checkout_path") or f"the {group['project']} checkout"
        refs = ", ".join(group.get("public_refs") or [])
        parts.append(
            f"{group['count']} runnable in {group['project']} ({refs})"
            f" — invoke /yoke do from {checkout}"
        )
    elsewhere = "; ".join(parts) if parts else "no runnable items in other projects"
    if unmapped:
        return f"this folder is not a mapped checkout; {elsewhere}"
    home = home_project or "this project"
    return f"nothing runnable in {home}; {elsewhere}"


def enrich_elsewhere_checkout_paths(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fill blank checkout paths from this machine's mapping (HTTPS client)."""
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id

    context = payload.get("context") if isinstance(payload.get("context"), dict) else payload
    groups = context.get("runnable_elsewhere") if isinstance(context, dict) else None
    if not isinstance(groups, list):
        return payload
    for group in groups:
        if not isinstance(group, dict) or group.get("checkout_path"):
            continue
        project_id = group.get("project_id")
        if project_id is None:
            continue
        checkout = checkout_for_project_id(int(project_id))
        if checkout is not None:
            group["checkout_path"] = str(checkout)
    if isinstance(payload.get("context"), dict):
        note = payload["context"].get("runnable_elsewhere_note")
        if note:
            payload["context"]["runnable_elsewhere_note"] = render_runnable_elsewhere_note(
                groups,
                home_project=payload["context"].get("workspace_home_project"),
                unmapped=bool(payload["context"].get("workspace_unmapped")),
            )
    return payload


def _mapped_project_id(workspace: str) -> Optional[int]:
    try:
        from yoke_core.domain import machine_config

        mapped = machine_config.project_id(Path(workspace))
    except Exception:
        return None
    return int(mapped) if mapped is not None else None


def _session_project_id(conn: Any, session_id: str) -> Optional[int]:
    try:
        row = conn.execute(
            "SELECT project_id FROM harness_sessions WHERE session_id=%s",
            (session_id,),
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    raw = row["project_id"] if hasattr(row, "keys") else row[0]
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _home_slug(conn: Any, home_project_id: Optional[int]) -> Optional[str]:
    if home_project_id is None:
        return None
    try:
        from yoke_core.domain.project_identity import resolve_project_slug

        return resolve_project_slug(conn, int(home_project_id))
    except Exception:
        return str(home_project_id)


def _project_id_for_slug(conn: Any, slug: str) -> Optional[int]:
    if not slug or slug == "unknown" or conn is None:
        return None
    try:
        from yoke_core.domain.project_identity import resolve_project_id

        return int(resolve_project_id(conn, slug))
    except Exception:
        return None


def _step_is_home(step: Any, home_project_id: Optional[int], home_slug: Optional[str]) -> bool:
    if home_project_id is None:
        return False
    label = (getattr(step, "project", None) or "").strip()
    if not label:
        return False
    return label == (home_slug or "") or label == str(home_project_id)


def _step_refs(steps: List[Any], conn: Any) -> List[str]:
    from yoke_core.domain.sessions_queries_base import display_claim_item_id

    return [
        display_claim_item_id(str(getattr(step, "item_id", "")), conn)
        or str(getattr(step, "item_id", ""))
        for step in steps
    ]


def _append_workspace_home_diagnostic(
    schedule: Any,
    *,
    before: int,
    eliminated: int,
    home_slug: Optional[str],
    eliminated_items: List[str],
) -> None:
    diagnostics = getattr(schedule, "offer_diagnostics", None)
    if not isinstance(diagnostics, dict):
        return
    entry = {
        "filter": "workspace_home",
        "candidates_before": before,
        "eliminated": eliminated,
        "home_project": home_slug,
        "eliminated_items": eliminated_items,
    }
    chain = list(diagnostics.get("elimination_chain") or [])
    chain.append(entry)
    diagnostics["elimination_chain"] = chain


__all__ = [
    "apply_workspace_home_filter",
    "build_runnable_elsewhere_context",
    "enrich_elsewhere_checkout_paths",
    "group_runnable_elsewhere",
    "render_runnable_elsewhere_note",
    "resolve_offer_home_project",
    "workspace_home_filter_requested",
]
