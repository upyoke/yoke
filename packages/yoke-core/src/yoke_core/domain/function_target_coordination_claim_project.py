"""Name the project a coordination-claim request is aimed at.

A holder releases by the row id its acquire handed back, and lists by the
session holding them; neither payload carries a project, and both were denied
for failing to name a target the caller cannot be expected to know. The claim
row and the session row each already record the project, so the target is read
from them and the ordinary scoped permission check then runs against it
unchanged — this resolves the target, it does not decide the answer.
"""

from __future__ import annotations

from typing import Any, Collection, Optional

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.function_target_row_project import (
    resolve_work_claim_project,
    slug_for_project_id,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_QA_ADMISSION,
    from_row as work_claim_target_from_row,
)


def resolve_coordination_claim_project_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None,
) -> tuple[int, str] | None:
    """Resolve the project from the addressed claim, else the named session."""
    payload = request.payload or {}
    raw_claim_id = payload.get("claim_id")
    if raw_claim_id is not None:
        return _project_of_claim(
            conn, raw_claim_id, visible_project_ids=visible_project_ids
        )
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return None
    row = conn.execute(
        "SELECT project_id FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return _visible(conn, int(row[0]), visible_project_ids)


def _project_of_claim(
    conn: Any,
    raw_claim_id: Any,
    *,
    visible_project_ids: Collection[int] | None,
) -> tuple[int, str] | None:
    """Read a coordination claim's own project out of its typed scope.

    A shared-operation claim carries the project in its scope rather than
    through an owning item, so the generic work-claim resolver answers nothing
    for it; that silence is what denied a release addressed only by row id.
    ``qa_admission`` is the remaining exception: its scope names only the
    machine, so the holding session's project is the permission target.
    """
    try:
        claim_id = int(raw_claim_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        "SELECT target_kind, scope FROM work_claims WHERE id=%s",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None
    target = work_claim_target_from_row({"target_kind": row[0], "scope": row[1]})
    scoped_project: Optional[int] = target.project_id
    if scoped_project is not None:
        return _visible(conn, int(scoped_project), visible_project_ids)
    if target.kind == TARGET_KIND_QA_ADMISSION:
        return _project_of_holding_session(
            conn, claim_id, visible_project_ids=visible_project_ids
        )
    return resolve_work_claim_project(
        conn, claim_id, visible_project_ids=visible_project_ids
    )


def _project_of_holding_session(
    conn: Any,
    claim_id: int,
    *,
    visible_project_ids: Collection[int] | None,
) -> tuple[int, str] | None:
    """Resolve a machine-scoped claim through the session that holds it.

    ``qa_admission`` names only the physical host, so the claim row has no
    project for the ordinary scoped permission check. The acquire already
    ran under a session that recorded a project; reading that session is
    what lets the holder release by claim id instead of being denied as
    an untargeted project-scoped write.
    """
    row = conn.execute(
        "SELECT hs.project_id FROM work_claims wc "
        "JOIN harness_sessions hs ON hs.session_id = wc.session_id "
        "WHERE wc.id=%s",
        (claim_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return _visible(conn, int(row[0]), visible_project_ids)


def _visible(
    conn: Any,
    project_id: int,
    visible_project_ids: Collection[int] | None,
) -> tuple[int, str] | None:
    if visible_project_ids is not None and project_id not in visible_project_ids:
        return None
    return project_id, slug_for_project_id(conn, project_id)


__all__ = ["resolve_coordination_claim_project_context"]
