"""Persist a native title observed by the client on prompt and Stop."""

from yoke_contracts.hook_runner.client_facts import HARNESS_TITLE_KEY, read_client_fact
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import placeholder
from yoke_core.hooks.types import HookDecision, Next, Outcome


def evaluate(context):
    value = read_client_fact(context.payload, HARNESS_TITLE_KEY)
    if isinstance(value, str) and value.strip() and context.session_id:
        conn = connect()
        try:
            p = placeholder(conn)
            conn.execute(
                f"UPDATE harness_sessions SET harness_title={p} WHERE session_id={p}",
                (value, context.session_id),
            )
            conn.commit()
        finally:
            conn.close()
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
