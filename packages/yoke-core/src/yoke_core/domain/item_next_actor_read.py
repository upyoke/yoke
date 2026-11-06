"""Batched next-action enrichment for item lists and cards."""

from yoke_core.domain.next_actor import item_next_actor, action
from yoke_core.domain.next_actor_facts import next_actor_facts, _rows
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.session_state import session_presence, session_state
from yoke_core.domain.session_automatic_reclaim import reclaim_facts
from yoke_core.domain.frontier_group import frontier_group
from yoke_core.domain.frontier_landing_wait import committed_lane_item_ids
from yoke_contracts.lifecycle_status import ENGINE_EXCEPTIONAL_STAGE_IDS


def item_action_states(conn, rows, claims, runtimes):
    ids = [int(row["internal_id"]) for row in rows]
    sessions = {str(claim["session_id"]) for claim in claims.values()}
    holders = {}
    if sessions:
        slots = ",".join(placeholder(conn) for _ in sessions)
        holders = {
            row["session_id"]: row
            for row in _rows(
                conn,
                f"SELECT * FROM harness_sessions WHERE session_id IN ({slots})",
                sessions,
            )
        }
    session_facts, item_facts = next_actor_facts(
        conn, session_ids=sessions, item_ids=ids
    )
    holders = {row["session_id"]: row for row in reclaim_facts(
        conn, holders.values(), session_facts_complete=True
    )}
    committed = committed_lane_item_ids(conn, ids)
    result = {}
    for row in rows:
        iid = int(row["internal_id"])
        runtime = runtimes[int(row["workflow_version_id"])]
        sid = (claims.get(iid) or {}).get("session_id")
        holder = holders.get(sid)
        if holder:
            holder = {
                **holder,
                **session_facts.get(sid, {}),
                "presence": session_presence(holder),
            }
        state = {
            **row, **item_facts.get(iid, {}),
            "terminal": row.get("finished", row["status"] in runtime.terminal_stage_ids),
        }
        next_actor = item_next_actor(
            state,
            holder=holder if holder and holder["presence"] != "ended" else None,
        )
        if row["status"] in ENGINE_EXCEPTIONAL_STAGE_IDS and not state["terminal"]:
            next_actor = action("parent_or_steering", "work_halted", row.get("updated_at"))
        dependency = state.get("dependency_wait") or {}
        stage = runtime.stage(str(row["status"])) or {}
        group = frontier_group(
            {
                **state, "next_actor": next_actor,
                "exceptional": row["status"] in ENGINE_EXCEPTIONAL_STAGE_IDS,
                "release_stage": stage.get("board_bucket") == "release",
                "dependency_holds_pickup": bool(dependency) and (
                    dependency.get("gate_point") == "activation" or iid in committed
                ),
            },
            [session_state(holder)] if holder else [],
        )
        result[iid] = {"next_actor": next_actor, "frontier_group": group}
    return result
