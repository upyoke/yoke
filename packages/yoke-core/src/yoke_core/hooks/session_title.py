"""Persist a native title observed by the client on prompt and Stop."""

from yoke_contracts.hook_runner.client_facts import HARNESS_TITLE_KEY, read_client_fact
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import placeholder
from yoke_core.hooks.types import HookDecision, Next, Outcome


def evaluate(context):
    value = read_client_fact(context.payload, HARNESS_TITLE_KEY)
    if _valid_title_fact(context.payload) and context.session_id:
        conn = connect()
        try:
            p = placeholder(conn)
            conn.execute(
                f"UPDATE harness_sessions SET harness_title={p} WHERE session_id={p} "
                f"AND COALESCE(harness_title,'')<>COALESCE({p},'')",
                (value, context.session_id, value),
            )
            conn.commit()
        finally:
            conn.close()
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def confirmed_title(session_id, payload):
    expected = read_client_fact(payload, HARNESS_TITLE_KEY)
    if not session_id or not _valid_title_fact(payload):
        return None
    conn = None
    try:
        conn = connect()
        row = conn.execute(
            f"SELECT harness_title FROM harness_sessions WHERE session_id={placeholder(conn)}",
            (session_id,),
        ).fetchone()
        return {"value": expected} if row and row[0] == expected else None
    except Exception:
        return None  # No receipt means the client retries on the next hook.
    finally:
        if conn is not None:
            conn.close()


def _valid_title_fact(payload):
    raw = payload.get(HARNESS_TITLE_KEY)
    if not isinstance(raw, dict) or raw.get("schema") != 1 or "value" not in raw:
        return False
    value = raw["value"]
    return value is None or (isinstance(value, str) and bool(value.strip()))
