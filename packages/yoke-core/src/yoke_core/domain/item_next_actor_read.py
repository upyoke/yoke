"""Batched next-action enrichment for item lists and cards."""

from yoke_core.domain.next_actor import item_next_actor
from yoke_core.domain.next_actor_facts import next_actor_facts, _rows
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.session_state import session_presence


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
        result[iid] = item_next_actor(
            {
                **row,
                **item_facts.get(iid, {}),
                "terminal": row["status"] in runtime.terminal_stage_ids,
            },
            holder=holder,
        )
    return result
