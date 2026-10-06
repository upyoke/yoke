"""The claim lookup read end to end through the real dispatcher.

``resolve_claim_worktrees`` decodes each holder's typed claim scope with a
strict key-for-key decoder, so anything the dispatcher boundary adds to a
response scope refuses the whole lookup. The sibling lookup tests stub the
dispatcher; this one routes ``claims.work.holder_list`` through
:func:`yoke_function_dispatch.dispatch` against a real database, the path a
local universe and the server both take.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest

from runtime.api.domain.strategy_execution_test_support import seed_session_claim
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.backlog_inserts import insert_item_worktree
from yoke_core.domain.verification_tree_binding import resolve_claim_worktrees
from yoke_core.domain.yoke_function_dispatch import dispatch

SESSION = "round-trip-session"
ITEM_ID = 4242
LANE = "/repo/.worktrees/round-trip-lane"


def _dispatch_in_process(monkeypatch) -> None:
    import yoke_core.api.service_client_structured_api_adapter as adapter

    def _call(*, function_id, target, payload=None, **_kwargs):
        return dispatch(
            FunctionCallRequest(
                function=function_id,
                actor=ActorContext(actor_id=None, session_id=SESSION),
                target=target,
                payload=payload or {},
            ),
            ambient_session_id=SESSION,
        )

    monkeypatch.setattr(adapter, "call_dispatcher", _call)


def test_holder_scope_survives_the_dispatcher_and_decodes(test_db, monkeypatch):
    insert_item(test_db, id=ITEM_ID, title="round-trip item")
    seed_session_claim(test_db, ITEM_ID, SESSION)
    insert_item_worktree(test_db, item_id=ITEM_ID, branch="round-trip", path=LANE)
    _dispatch_in_process(monkeypatch)

    lookup = resolve_claim_worktrees(SESSION)

    assert lookup.reachable is True, lookup.detail
    assert lookup.worktrees == (LANE,)
    assert lookup.lane_item_id == f"YOK-{ITEM_ID}"
