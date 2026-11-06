"""Pinned stage, Frontier home and progress for every item read surface."""

from yoke_core.domain.item_next_actor_read import item_action_states
from yoke_core.domain.item_page_claims import active_item_claims
from yoke_core.domain.session_item_stage_states import _item_rows, item_stage_states
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.schema_common import _table_exists

STATE_FIELDS = ("stage", "home_section", "next_actor", "progress")


def item_display_states(conn, item_ids):
    """Read one shared projection for CLI rows, web cards and item details."""
    items = _item_rows(conn, tuple(dict.fromkeys(int(i) for i in item_ids)))
    if not items:
        return {}
    slots = ",".join(placeholder(conn) for _ in items)
    facts = conn.execute(
        "SELECT id,title,spec,frozen,updated_at,created_at FROM items "
        f"WHERE id IN ({slots})", tuple(items),
    ).fetchall()
    for fact in facts:
        items[int(fact["id"])].update(dict(fact))
    claims = active_item_claims(conn, items)
    runtimes = {int(row["workflow_version_id"]): row["runtime"] for row in items.values()}
    from yoke_core.domain.item_finished_times import is_finished
    from yoke_core.domain.item_spec_completeness import item_needs_spec

    actions = item_action_states(conn, [
        {**row, "internal_id": iid, "finished": is_finished(row["runtime"], row["status"]),
         "needs_spec": item_needs_spec(row)} for iid, row in items.items()
    ], claims, runtimes)
    tasks = {}
    if _table_exists(conn, "epic_tasks"):
        slots = ",".join(placeholder(conn) for _ in items)
        for row in conn.execute(
            f"SELECT epic_id,status FROM epic_tasks WHERE epic_id IN ({slots})", tuple(items)
        ).fetchall():
            tasks.setdefault(int(row["epic_id"]), []).append(row["status"])
    result = {}
    for iid, row in items.items():
        runtime = row["runtime"]
        progress = {"stages": item_stage_states(runtime, row["status"])}
        if runtime.policies["generated_children"] == "epic_tasks":
            statuses = tasks.get(iid, [])
            progress["tasks"] = {
                "total": len(statuses),
                "complete": sum(s in runtime.successful_task_stage_ids for s in statuses),
            }
        result[iid] = {
            "stage": {"id": row["status"], "label": runtime.stage_label(row["status"])},
            "frontier_group": actions[iid]["frontier_group"],
            "home_section": actions[iid]["frontier_group"]["section"],
            "next_actor": actions[iid]["next_actor"],
            "progress": progress,
        }
    return result
