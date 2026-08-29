"""items.public_ref.lookup returns PREFIX-N handles for internal ids."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.items_public_ref import handle_items_public_ref_lookup


def test_lookup_requires_global_target() -> None:
    outcome = handle_items_public_ref_lookup(
        FunctionCallRequest(
            function="items.public_ref.lookup",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=1),
            payload={"item_ids": [1]},
        )
    )
    assert outcome.error is not None
    assert outcome.error.code == "target_invalid"


def test_lookup_rejects_empty_ids() -> None:
    outcome = handle_items_public_ref_lookup(
        FunctionCallRequest(
            function="items.public_ref.lookup",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="global"),
            payload={"item_ids": []},
        )
    )
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
