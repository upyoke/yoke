"""Internal server-side reads/writes for the merge-worktree finalize path.

Two merge-engine control-plane touches used to open a local ``connect()``
inside the engine, which fails over an https control plane (no local
Postgres):

* the fail-closed prune authority verdict (does a DB-owned terminal
  worktree / branch still hold active authority, or is it safe to prune?),
  and
* the integration-tree verification resolution (materialize any attached
  release-transition QA plan, then resolve a project-owned registered
  verification command).

These handlers relay both touches server-side (dispatched in-process
against a local Postgres connection, or over https server-side) while the
merge engine keeps every git and filesystem operation — worktree removal,
branch deletion, test execution — local.

Each handler is a thin wrapper over unchanged domain state: the prune
verdict wraps the unchanged
:func:`yoke_core.engines.merge_prune_authority.terminal_owner` /
:func:`~yoke_core.engines.merge_prune_authority.has_active_authority`
fail-closed logic, and the post-rebase read wraps
:func:`yoke_core.domain.qa_plan_attachments.materialize_for_item` plus the
registered project Command-plan reader. The prune/keep
decision and every engine-side narrative stay client-side; these handlers
return only the raw verdict data. They are ``adapter_status='internal'``
(merge glue, never an agent CLI surface), so they carry no CLI adapter
inventory row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class PruneAuthorityRequest(BaseModel):
    branch: str = Field(..., min_length=1)
    path: Optional[str] = None


class PruneAuthorityResponse(BaseModel):
    prunable: bool
    reason: str


class PostRebaseRequirementRequest(BaseModel):
    transition_id: str = Field(default="release", min_length=1)


class PostRebaseRequirementResponse(BaseModel):
    requirement_id: Optional[int] = None
    project: str
    scope: str
    command: str
    covering_runs: list[dict[str, Any]] = Field(default_factory=list)


def _covering_runs(
    conn: Any, marker: str, item_id: int, scope: str, command: str,
) -> list[dict[str, Any]]:
    """Passing QA runs whose evidence can waive a same-tree re-execution.

    A run qualifies when it passed and recorded the exact commit it covered
    (``raw_result.verification_tree.head_sha``), and its requirement's
    execution family vouches for the resolved verification scope: a ``ci_run``
    case executed the project's declared CI workflow (the merge-path suite
    authority regardless of the registered command's scope), while a local
    ``worktree_run`` case covers only the identical registered command.
    The client compares git tree identity; unparseable evidence is dropped
    so the caller falls back to executing the suite.
    """
    from yoke_core.domain.db_helpers import query_rows
    from yoke_core.domain.json_helper import loads_text

    def _loads_or_none(text: str) -> Any:
        try:
            return loads_text(text)
        except Exception:  # noqa: BLE001 - malformed evidence is non-covering
            return None

    rows = query_rows(
        conn,
        "SELECT r.id AS run_id, r.raw_result, q.runner_id, q.method_config "
        "FROM qa_runs r JOIN qa_requirements q ON q.id = r.qa_requirement_id "
        f"WHERE q.item_id={marker} AND r.verdict='pass'",
        (item_id,),
    )
    covering: list[dict[str, Any]] = []
    for row in rows:
        raw = _loads_or_none(row["raw_result"] or "")
        if not isinstance(raw, dict):
            continue
        tree = raw.get("verification_tree")
        head_sha = (
            str(tree.get("head_sha") or "").strip()
            if isinstance(tree, dict) else ""
        )
        if not head_sha:
            continue
        runner_id = str(row["runner_id"] or "")
        if runner_id == "worktree_run":
            config = _loads_or_none(row["method_config"] or "")
            if not isinstance(config, dict):
                continue
            if str(config.get("command") or "") != command:
                continue
            if str(config.get("registered_scope") or "") != scope:
                continue
        elif runner_id != "ci_run":
            continue
        covering.append(
            {
                "run_id": int(row["run_id"]),
                "head_sha": head_sha,
                "runner_id": runner_id,
            }
        )
    return covering


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_prune_authority_verdict(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the fail-closed prune verdict for a branch / worktree identity.

    ``prunable`` is True only when a unique terminal DB owner exists AND no
    active authority holds it — exactly the two-gate decision the engine
    computed inline. ``reason`` is ``no_terminal_owner`` (keep silently),
    ``active_authority`` (keep with a "Preserving actively claimed"
    narrative in loop-one), or ``prunable``. The terminal-success set and
    every git check (clean / merged / removal) stay engine-owned; this read
    reports only the DB authority verdict.
    """
    try:
        body = PruneAuthorityRequest.model_validate(request.payload)
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"prune authority payload invalid: {exc}")

    from yoke_core.engines.merge_prune_authority import (
        has_active_authority,
        terminal_owner,
    )

    path = Path(body.path) if body.path else None
    try:
        with _connect_rw() as conn:
            owner = terminal_owner(conn, branch=body.branch, path=path)
            if owner is None:
                verdict = {"prunable": False, "reason": "no_terminal_owner"}
            elif has_active_authority(conn, owner, path):
                verdict = {"prunable": False, "reason": "active_authority"}
            else:
                verdict = {"prunable": True, "reason": "prunable"}
    except Exception as exc:  # noqa: BLE001 - connect failure == authority unavailable
        return _err("prune_authority_read_failed", str(exc))

    return HandlerOutcome(result_payload=verdict, primary_success=True)


def handle_post_rebase_requirement(request: FunctionCallRequest) -> HandlerOutcome:
    """Resolve local verification for the item's integrated candidate tree.

    Any effective QA plan attached to the supplied transition is materialized
    before command resolution. Workflows without that transition commonly
    have no attachment there; checking first avoids manufacturing a transition
    requirement just to run the project-wide integration gate. Once any
    attached plan is snapshotted, prefer the registered ``full`` command and
    fall back to ``quick``. Both local and CI-routed Command cases retain this
    project-owned command in their immutable method configuration, so the
    merge engine can deliberately execute it against the local candidate tree.

    Missing command configuration and every materialization/read failure are
    structured failures. The client treats every failed dispatcher response as
    merge-blocking, so a registered project can never advance without an
    executable verification contract.
    """
    item_id = request.target.item_id
    if item_id is None:
        return _err("target_invalid", "post_rebase_requirement requires target.item_id")
    try:
        body = PostRebaseRequirementRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"post_rebase payload invalid: {exc}")

    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_command_plans import (
        list_registered_commands_for_project_id,
    )
    from yoke_core.domain.qa_plan_attachments import (
        has_attached_plans,
        materialize_for_item,
    )

    try:
        with _connect_rw() as conn:
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            item = query_one(
                conn,
                "SELECT i.project_id, p.slug AS project "
                "FROM items i JOIN projects p ON p.id=i.project_id "
                f"WHERE i.id={marker}",
                (int(item_id),),
            )
            if item is None:
                raise LookupError(f"item {item_id} not found")
            project_id = int(item["project_id"])
            project = str(item["project"])
            if has_attached_plans(
                conn, item_id=int(item_id), transition_id=body.transition_id,
            ):
                materialize_for_item(
                    conn,
                    item_id=int(item_id),
                    transition_id=body.transition_id,
                )
            commands = list_registered_commands_for_project_id(conn, project_id)
            selected = next(
                (
                    (scope, commands[scope])
                    for scope in ("full", "quick")
                    if scope in commands
                ),
                None,
            )
            covering = (
                _covering_runs(
                    conn, marker, int(item_id), selected[0], selected[1],
                )
                if selected is not None else []
            )
    except Exception as exc:  # noqa: BLE001 - materialize failure blocks the merge
        return _err("post_rebase_requirement_failed", str(exc))

    if selected is None:
        return _err(
            "post_rebase_verification_missing",
            f"project {project!r} has no executable registered full or quick command",
        )
    scope, command = selected
    return HandlerOutcome(
        result_payload={
            "requirement_id": None,
            "project": project,
            "scope": scope,
            "command": command,
            "covering_runs": covering,
        },
        primary_success=True,
    )


__all__ = [
    "PostRebaseRequirementRequest",
    "PostRebaseRequirementResponse",
    "PruneAuthorityRequest",
    "PruneAuthorityResponse",
    "handle_post_rebase_requirement",
    "handle_prune_authority_verdict",
]
