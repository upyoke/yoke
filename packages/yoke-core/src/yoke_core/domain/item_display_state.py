"""Pinned stage, Frontier home and progress for every item read surface."""

from yoke_core.domain.item_next_actor_read import item_action_states
from yoke_core.domain.item_page_claims import active_item_claims
from yoke_core.domain.session_item_stage_states import _item_rows, item_stage_states
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.schema_common import _table_exists

STATE_FIELDS = ("stage", "home_section", "next_actor", "progress")


def home_section(row, *, claimant=None, ready=False, blockers=()):
    """Choose one home; holding work and blocking it remain separate facts."""
    runtime = row["runtime"]
    if row["status"] in runtime.terminal_stage_ids:
        return "done"
    if row["status"] == "release":
        return "release"
    if row.get("frozen"):
        return "on_hold"
    state = (claimant or {}).get("session_state") or {}
    if state and state["presence"] != "ended" and (
        state["presence"] == "present" or state["intent"]["state"] != "none"
    ):
        return "active"
    starting = [entry for entry in blockers if entry.get("holds_pickup", True)]
    if starting or row.get("blocked"):
        return "waiting" if any(e.get("blocking_item") for e in starting) else "on_hold"
    return "on_hold" if claimant else "ready" if ready else "on_hold"


def item_display_states(conn, item_ids, *, frontier=None):
    """Read one shared projection for CLI rows, web cards and item details."""
    items = _item_rows(conn, tuple(dict.fromkeys(int(i) for i in item_ids)))
    if not items:
        return {}
    if frontier is None:
        from yoke_core.domain.frontier_list_read import list_frontier

        frontier = list_frontier(include_state=False)
    ready = {str(row.get("public_ref") or row.get("item_id")) for row in frontier["ready_rows"]}
    blocked = {}
    for row in frontier["blocked_rows"]:
        blocked.setdefault(str(row.get("public_ref") or row.get("item_id")), []).append(row)
    claims = active_item_claims(conn, items)
    sessions = {}
    if claims:
        from yoke_core.domain.sessions_list_read import list_sessions

        sessions = {row["session_id"]: row for row in list_sessions(
            session_ids=[claim["session_id"] for claim in claims.values()], limit=None
        )}
    runtimes = {int(row["workflow_version_id"]): row["runtime"] for row in items.values()}
    actions = item_action_states(conn, [
        {**row, "internal_id": iid} for iid, row in items.items()
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
        ref = row["public_ref"]
        progress = {"stages": item_stage_states(runtime, row["status"])}
        if runtime.policies["generated_children"] == "epic_tasks":
            statuses = tasks.get(iid, [])
            progress["tasks"] = {
                "total": len(statuses),
                "complete": sum(s in runtime.successful_task_stage_ids for s in statuses),
            }
        result[iid] = {
            "stage": {"id": row["status"], "label": runtime.stage_label(row["status"])},
            "home_section": home_section(
                row, claimant=sessions.get((claims.get(iid) or {}).get("session_id")),
                ready=ref in ready, blockers=blocked.get(ref, ()),
            ),
            "next_actor": actions[iid],
            "progress": progress,
        }
    return result
