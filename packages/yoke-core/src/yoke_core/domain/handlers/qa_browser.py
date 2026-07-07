"""Browser-QA orchestration handlers — the server half of the browser flow.

The browser-QA orchestrator (``yoke_core.domain.browser_qa``) executes
scenarios on the CLIENT machine (Playwright daemon, screenshots) while every
DB leg routes through four function ids, so the flow works identically from
a Yoke checkout on a local-postgres env and from an external project over
the https relay:

- ``qa.browser_context.get`` (this module) — one batched read: the item's
  browser-kind ``qa_requirements`` rows plus (when ``expected_branch`` is
  supplied) the latest ``ephemeral_environments.deployed_sha`` for the
  freshness gate and the branch's latest recorded ephemeral preview URL
  (``ephemeral_url`` — the advance gate-entry read that replaces raw
  client SQL).
- ``qa.run.add`` / ``qa.run.complete`` / ``qa.artifact.add`` — the write
  half, hosted in the companion module
  :mod:`yoke_core.domain.handlers.qa_browser_writes` so each file stays
  under the 350-line cap (the ``qa.py`` / ``qa_run.py`` convention).

Write handlers carry ``claim_required_kind="item"`` exactly like
``qa.run.record_verdict``; this read carries no claim and tolerates absent
ambient sessions (board.data.get precedent).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_core.domain.handlers.qa import _error, _p
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class QaBrowserContextGetRequest(BaseModel):
    project: str
    expected_branch: Optional[str] = None


class QaBrowserContextGetResponse(BaseModel):
    item_id: int
    requirements: List[Dict[str, Any]]
    deployed_sha: Optional[str] = None
    deployment_recorded: bool = False
    # Latest non-empty ephemeral_environments.url for (project, branch);
    # None when no preview URL was ever recorded for the branch.
    ephemeral_url: Optional[str] = None


def handle_qa_browser_context_get(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_rows
    from yoke_core.domain.project_identity import resolve_project_id

    target = request.target
    item_id = target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.browser_context.get requires target.item_id",
        )
    payload = request.payload or {}
    project = payload.get("project")
    expected_branch = payload.get("expected_branch")
    if not isinstance(project, str) or not project:
        return _error(
            "payload_invalid", "project is required",
            jsonpath="$.payload.project",
        )

    conn = connect()
    try:
        p = _p(conn)
        req_rows = query_rows(
            conn,
            "SELECT id, qa_kind, success_policy FROM qa_requirements "
            f"WHERE item_id = {p} AND qa_kind IN ('browser_smoke', 'browser_diff') "
            "AND waived_at IS NULL ORDER BY id",
            (int(item_id),),
        )
        requirements = [
            {
                "id": int(row["id"]),
                "qa_kind": str(row["qa_kind"]),
                "success_policy": row["success_policy"],
            }
            for row in req_rows
        ]

        deployed_sha: Optional[str] = None
        deployment_recorded = False
        ephemeral_url: Optional[str] = None
        if expected_branch:
            project_id = resolve_project_id(conn, project)
            env_rows = query_rows(
                conn,
                "SELECT deployed_sha FROM ephemeral_environments "
                f"WHERE project_id = {p} AND branch = {p} "
                "ORDER BY id DESC LIMIT 1",
                (project_id, str(expected_branch)),
            )
            if env_rows:
                deployment_recorded = True
                deployed_sha = env_rows[0]["deployed_sha"] or None
            # Latest row that actually recorded a preview URL — the
            # newest row may predate the URL write, so this read keeps
            # its own predicate (the gate-entry semantics the advance
            # skill previously issued as raw client SQL).
            url_rows = query_rows(
                conn,
                "SELECT url FROM ephemeral_environments "
                f"WHERE project_id = {p} AND branch = {p} "
                "AND url IS NOT NULL AND url <> '' "
                "ORDER BY id DESC LIMIT 1",
                (project_id, str(expected_branch)),
            )
            if url_rows:
                ephemeral_url = str(url_rows[0]["url"])
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            # Echo the resolved numeric id so ref-shaped callers (the
            # dispatcher resolves target.item_ref before this handler
            # runs) learn it without a second round trip.
            "item_id": int(item_id),
            "requirements": requirements,
            "deployed_sha": deployed_sha,
            "deployment_recorded": deployment_recorded,
            "ephemeral_url": ephemeral_url,
        },
        primary_success=True,
    )


__all__ = [
    "QaBrowserContextGetRequest", "QaBrowserContextGetResponse",
    "handle_qa_browser_context_get",
]
