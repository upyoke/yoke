"""Render the operator-facing ``## Path Claims`` body section.

Pure helper — given an item id and an open DB connection it returns
the rendered section string, or ``None`` when the item has no claims
attached. Mirrors the
:mod:`yoke_core.domain.render_body_db_claim` shape so the parent
:mod:`yoke_core.domain.render_body` only carries a thin call site.

Render policy:

* No claims attached → return ``None``. The body skips the section so
  unrelated items don't grow boilerplate.
* Claims attached → render every claim grouped by id with declared
  coverage, amendment history, and current blocking conflicts. The
  header surfaces state, integration target, actor, and session for
  the cold-start question.

The renderer reads the read-API projection
(:func:`yoke_core.domain.path_claims_read.item_view`) verbatim — it
does not re-query the DB itself for claim attributes. Side effects are
limited to the read-API queries the projection runs.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_read import item_view
from yoke_core.domain.path_targets_states import OBSERVED, PLANNED


PATH_CLAIMS_HEADING = "## Path Claims"


def _render_claim(claim: dict) -> List[str]:
    """Return the rendered lines for one claim entry.

    Operator perspective: every value the cold-start agent needs lives
    on one ``- **Field:** value`` line so it scans top-to-bottom; lists
    (declared coverage, amendments, conflicts) indent under their
    parent so the visual hierarchy matches the section's intent.
    """
    lines: List[str] = []
    cid = int(claim["id"])
    state = str(claim["state"])
    target = str(claim.get("integration_target") or "")
    lines.append(f"### Claim `{cid}` — `{state}` on `{target}`")
    lines.append("")
    owner_kind = claim.get("owner_kind")
    if owner_kind:
        lines.append(f"- **Owner kind:** `{owner_kind}`")
        if owner_kind == "item" and claim.get("owner_item_id") is not None:
            lines.append(f"  - Owner item id: `{claim['owner_item_id']}`")
        elif owner_kind == "session" and claim.get("owner_session_id"):
            lines.append(f"  - Owner session id: `{claim['owner_session_id']}`")
        elif owner_kind == "process" and claim.get("owner_work_claim_id") is not None:
            lines.append(
                f"  - Owner work claim id: `{claim['owner_work_claim_id']}`"
            )
    reg_actor = claim.get("registered_by_actor_id")
    reg_session = claim.get("registered_by_session_id")
    if reg_actor is not None or reg_session:
        bits: List[str] = []
        if reg_actor is not None:
            bits.append(f"actor=`{reg_actor}`")
        if reg_session:
            bits.append(f"session=`{reg_session}`")
        lines.append(f"- **Registered by:** {' '.join(bits)}")
    actor = claim.get("actor_id")
    if actor is not None:
        lines.append(f"- **Actor id:** `{actor}`")
    session_id = claim.get("session_id")
    if session_id:
        lines.append(f"- **Session id:** `{session_id}`")
    item_id = claim.get("item_id")
    if item_id is not None:
        lines.append(f"- **Item id:** `{item_id}`")
    if claim.get("base_commit_sha"):
        lines.append(f"- **Base commit SHA:** `{claim['base_commit_sha']}`")
    registered = claim.get("registered_at")
    if registered:
        lines.append(f"- **Registered at:** `{registered}`")
    activated = claim.get("activated_at")
    if activated:
        lines.append(f"- **Activated at:** `{activated}`")
    released = claim.get("released_at")
    if released:
        lines.append(f"- **Released at:** `{released}`")
    cancelled = claim.get("cancelled_at")
    if cancelled:
        lines.append(f"- **Cancelled at:** `{cancelled}`")
    blocked_reason = claim.get("blocked_reason")
    if blocked_reason:
        lines.append(f"- **Blocked reason:** {blocked_reason}")
    release_reason = claim.get("release_reason")
    if release_reason:
        lines.append(f"- **Release reason:** {release_reason}")
    cancel_reason = claim.get("cancel_reason")
    if cancel_reason:
        lines.append(f"- **Cancel reason:** {cancel_reason}")

    if str(claim.get("mode") or "") == "exception":
        reason = claim.get("exception_reason") or ""
        lines.append("- **No-Claim Exception**")
        lines.append(f"  - Reason: {reason}")
    else:
        targets = claim.get("declared_targets") or []
        if targets:
            lines.append("- **Declared coverage:**")
            for entry in targets:
                path = entry.get("path_string", "")
                raw_state = entry.get("materialization_state")
                state = str(raw_state) if raw_state else PLANNED
                tag = "" if state == OBSERVED else f" ({state})"
                lines.append(f"  - `{path}`{tag}")
        else:
            paths = claim.get("declared_paths") or []
            if paths:
                lines.append("- **Declared coverage:**")
                for path in paths:
                    lines.append(f"  - `{path}`")
            else:
                lines.append("- **Declared coverage:** _(empty)_")

    amendments = claim.get("amendments") or []
    if amendments:
        lines.append("- **Amendment history:**")
        for amendment in amendments:
            kind = amendment.get("amendment_kind", "")
            reason = amendment.get("reason") or ""
            applied = amendment.get("amended_at") or ""
            head = f"`{kind}`"
            tail_parts = [p for p in (reason, applied) if p]
            tail = f" — {' @ '.join(tail_parts)}" if tail_parts else ""
            lines.append(f"  - {head}{tail}")

    conflicts = claim.get("blocking_conflicts") or []
    if conflicts:
        lines.append("- **Current blocking conflicts:**")
        for conflict in conflicts:
            other_id = conflict.get("claim_id")
            other_state = conflict.get("state")
            other_paths = conflict.get("blocking_paths") or []
            head = f"claim `{other_id}` (`{other_state}`)"
            if other_paths:
                shown = ", ".join(f"`{p}`" for p in other_paths)
                lines.append(f"  - {head} on {shown}")
            else:
                lines.append(f"  - {head}")

    return lines


def render_path_claims_section(
    conn: Any, item_id: int
) -> Optional[str]:
    """Return the rendered ``## Path Claims`` section, or ``None``.

    Items with no claims attached return ``None`` so the body renderer
    skips the section. Items with claims always get the section, even
    when every claim is terminal — historical claims are part of the
    cold-start answer.
    """
    try:
        claims = item_view(conn, item_id)
    except db_backend.operational_error_types(conn):
        # path_claims absent (minimal / pre-migration DB). Key the swallow on
        # the actual connection dialect, not the ambient backend selector, so
        # fixture connections and shared Postgres connections both hit the
        # right backend error family. On a shared Postgres connection the
        # failed query aborts the transaction, so roll back to un-poison it
        # before the caller renders the remaining body sections; this is a
        # read-only render path, so nothing is lost.
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    if not claims:
        return None
    chunks: List[str] = [PATH_CLAIMS_HEADING, ""]
    for index, claim in enumerate(claims):
        chunks.extend(_render_claim(claim))
        if index < len(claims) - 1:
            chunks.append("")
    return "\n".join(chunks)


__all__ = [
    "PATH_CLAIMS_HEADING",
    "render_path_claims_section",
]
