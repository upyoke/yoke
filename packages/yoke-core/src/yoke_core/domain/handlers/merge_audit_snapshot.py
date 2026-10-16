"""Project-scoped control-plane facts for the machine-local merge audit."""

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome


class SnapshotRequest(BaseModel):
    pass


class SnapshotResponse(BaseModel):
    epics: list[dict] = Field(default_factory=list)
    standalone: list[dict] = Field(default_factory=list)


def handle_snapshot(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_rows, query_one
    from yoke_core.domain.function_target_resolution import resolve_project_context
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.task_lifecycle import TASK_TERMINAL_SUCCESS
    from yoke_core.domain.yoke_function_registry import lookup

    with connect() as conn:
        context = resolve_project_context(conn, lookup(request.function), request)
        if context is None:
            raise ValueError("project_required: pass --project P or an item reference")
        project_id, _ = context
        item_id = request.target.item_id
        selected = " AND i.id = %s" if item_id is not None else ""
        params = (project_id, item_id) if item_id is not None else (project_id,)
        rows = query_rows(
            conn,
            "SELECT i.id, i.title, i.status FROM items i WHERE i.project_id = %s"
            + selected
            + " AND EXISTS (SELECT 1 FROM epic_tasks t JOIN item_worktrees iw "
            "ON iw.id=t.item_worktree_id WHERE t.epic_id=i.id AND iw.state='active') "
            "ORDER BY i.id",
            params,
        )
        epics = []
        for row in rows:
            tasks = query_rows(
                conn,
                "SELECT t.task_num, t.title, t.status, iw.branch, iw.state "
                "FROM epic_tasks t LEFT JOIN item_worktrees iw ON iw.id=t.item_worktree_id "
                "WHERE t.epic_id=%s ORDER BY t.task_num",
                (row["id"],),
            )
            terminal = set(TASK_TERMINAL_SUCCESS)
            branches = {}
            for task in tasks:
                if task["state"] == "active" and task["branch"]:
                    branch = branches.setdefault(
                        task["branch"], {"total": 0, "done": 0}
                    )
                    branch["total"] += 1
                    branch["done"] += int(task["status"] in terminal)
            sim = query_one(
                conn,
                "SELECT result FROM epic_simulations WHERE epic_id=%s "
                "AND phase='integration' ORDER BY created_at DESC LIMIT 1",
                (row["id"],),
            )
            epics.append(
                {
                    "id": row["id"],
                    "public_ref": render_item_ref(conn, row["id"]),
                    "title": row["title"],
                    "status": row["status"],
                    "total": len(tasks),
                    "done": sum(t["status"] in terminal for t in tasks),
                    "simulation": (sim["result"] or "UNKNOWN") if sim else "MISSING",
                    "branches": branches,
                    "incomplete": [
                        dict(t) for t in tasks if t["status"] not in terminal
                    ],
                }
            )
        standalone = []
        if item_id is None:
            rows = query_rows(
                conn,
                "SELECT iw.branch, i.id, i.title, i.status FROM item_worktrees iw "
                "JOIN items i ON i.id=iw.item_id WHERE i.project_id=%s AND i.status='done' "
                "AND NOT EXISTS (SELECT 1 FROM epic_tasks t WHERE t.epic_id=i.id) "
                "ORDER BY i.id, iw.id",
                (project_id,),
            )
            standalone = [
                {**dict(row), "public_ref": render_item_ref(conn, row["id"])}
                for row in rows
            ]
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "epics": epics,
            "standalone": standalone,
        },
    )


def register(registry):
    registry.register(
        "merge.audit.snapshot",
        handle_snapshot,
        SnapshotRequest,
        SnapshotResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item", "global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        minimum_serving_version="next-release",
    )
