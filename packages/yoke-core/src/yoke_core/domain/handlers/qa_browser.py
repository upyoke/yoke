"""Browser-method execution handlers — server reads for one case.

The shared case runner executes one materialized Browser method requirement
on the client machine (Playwright daemon, screenshots) while every DB leg
routes through registered function ids:

- ``qa.browser_context.get`` (this module) — one requirement-scoped read:
  the named Browser-method case plus whichever deployment the case is
  about. A case that names a persistent environment — a frozen snapshot,
  ``target_env``, a run, or a run-member stage — is returned as
  ``deployment_target`` so freshness asks that host, never a branch
  preview. A run case also carries ``run_source``: the commit that run was
  pinned to deliver, which is the expectation its evidence is judged
  against. Only an unbound item case is about the branch preview: (when
  ``expected_branch`` is supplied) the latest
  ``ephemeral_environments.deployed_sha`` for the freshness gate and the
  branch's latest recorded ephemeral preview URL (``ephemeral_url`` — the
  advance gate-entry read that replaces raw client SQL). Preview fields
  stay empty on a bound persistent target, because that deployment is not
  found by slugifying a branch.
- ``qa.run.add`` / ``qa.run.complete`` / ``qa.artifact.add`` — the write
  half, hosted in the companion module
  :mod:`yoke_core.domain.handlers.qa_browser_writes` so each file stays
  under the 350-line cap (the ``qa.py`` / ``qa_run.py`` convention).

Write handlers carry ``claim_required_kind="qa_subject"`` exactly like
``qa.run.record_verdict``; this read carries no claim and tolerates absent
ambient sessions (board.data.get precedent).

A materialized Browser case names exactly one subject — the item it
verifies, or the deployment run it verifies — so this read accepts an
``item`` target or a ``deployment_run`` target and scopes the requirement
lookup to whichever the caller named.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_core.domain.handlers.qa import _error, _p
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)
from yoke_core.domain.browser_qa_case_target import (
    resolve_case_deployment_under_test,
)
from yoke_core.domain.browser_qa_deployment_identity import (
    resolve_deployment_under_test,
    resolve_run_pinned_source,
)


class QaBrowserContextGetRequest(BaseModel):
    project: str
    requirement_id: int
    expected_branch: Optional[str] = None


class QaBrowserContextGetResponse(BaseModel):
    item_id: Optional[int] = None
    deployment_run_id: Optional[str] = None
    requirements: List[Dict[str, Any]]
    deployed_sha: Optional[str] = None
    deployment_recorded: bool = False
    # Latest non-empty ephemeral_environments.url for (project, branch);
    # None when no preview URL was ever recorded for the branch. The three
    # fields above describe a branch preview and are meaningful only for an
    # item case.
    ephemeral_url: Optional[str] = None
    # The environment this case verifies when it names one (snapshot,
    # target_env, run, or run-member stage). None for an unbound preview.
    deployment_target: Optional[Dict[str, Any]] = None
    # The commit a run was pinned to deliver, and the branch labelling it.
    # Present only for a deployment-run case, which is judged against what
    # the run froze rather than against anything a caller supplies.
    run_source: Optional[Dict[str, str]] = None


def handle_qa_browser_context_get(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_rows
    from yoke_core.domain.project_identity import resolve_project_id

    target = request.target
    item_id = target.item_id
    deployment_run_id = target.deployment_run_id
    if (item_id is None) == (deployment_run_id is None):
        return _error(
            "target_invalid",
            "qa.browser_context.get requires exactly one subject: "
            "target.item_id for an item case, or target.deployment_run_id "
            "for a deployment-run case",
        )
    payload = request.payload or {}
    project = payload.get("project")
    expected_branch = payload.get("expected_branch")
    requirement_id = payload.get("requirement_id")
    if not isinstance(project, str) or not project:
        return _error(
            "payload_invalid",
            "project is required",
            jsonpath="$.payload.project",
        )
    if not isinstance(requirement_id, int):
        return _error(
            "payload_invalid",
            "requirement_id is required",
            jsonpath="$.payload.requirement_id",
        )

    subject_column = "item_id" if item_id is not None else "deployment_run_id"
    subject_value: Any = int(item_id) if item_id is not None else str(deployment_run_id)
    conn = connect()
    try:
        p = _p(conn)
        req_rows = query_rows(
            conn,
            "SELECT id, qa_kind, method_id, method_config, "
            "expected_outcome FROM qa_requirements "
            f"WHERE {subject_column} = {p} "
            "AND method_id IN ('browser-check', 'browser-inspection') "
            f"AND waived_at IS NULL AND id = {p}",
            (subject_value, int(requirement_id)),
        )
        requirements = [
            {
                "id": int(row["id"]),
                "qa_kind": str(row["qa_kind"]),
                "method_id": row["method_id"],
                "method_config": row["method_config"],
                "expected_outcome": row["expected_outcome"],
            }
            for row in req_rows
        ]

        deployed_sha: Optional[str] = None
        deployment_recorded = False
        ephemeral_url: Optional[str] = None
        deployment_target: Optional[Dict[str, Any]] = None
        run_source: Optional[Dict[str, str]] = None
        if deployment_run_id is not None:
            # What the run was pinned to deliver. The deployment path had no
            # expectation of its own before this, so a stage that certifies
            # production recorded captures bound to no commit at all.
            run_source = resolve_run_pinned_source(conn, str(deployment_run_id))
        bound = resolve_case_deployment_under_test(
            conn,
            requirement_id=int(requirement_id),
            project_id=resolve_project_id(conn, project),
        )
        if bound is not None:
            # A case that names an environment is about that environment,
            # whatever subject it hangs off. Answering with its own bound
            # target is what lets an item case verify the deployment it was
            # bound to instead of a branch preview it was never about.
            deployment_target = bound.as_payload()
        elif deployment_run_id is not None:
            # A run's deployment is the environment it targeted. Reading the
            # branch's preview rows here would answer about a host this run
            # never deployed, which is how a succeeded production release
            # ends up unable to prove itself.
            deployment_target = resolve_deployment_under_test(
                conn, str(deployment_run_id)
            ).as_payload()
        elif expected_branch:
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
            # dispatcher resolves target.public_ref before this handler
            # runs) learn it without a second round trip.
            "item_id": int(item_id) if item_id is not None else None,
            "deployment_run_id": (
                str(deployment_run_id) if deployment_run_id is not None else None
            ),
            "requirements": requirements,
            "deployed_sha": deployed_sha,
            "deployment_recorded": deployment_recorded,
            "ephemeral_url": ephemeral_url,
            "deployment_target": deployment_target,
            "run_source": run_source,
        },
        primary_success=True,
    )


__all__ = [
    "QaBrowserContextGetRequest",
    "QaBrowserContextGetResponse",
    "handle_qa_browser_context_get",
]
