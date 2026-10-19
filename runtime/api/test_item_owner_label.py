"""Item owners render as the actor's name plus its actor id."""

from __future__ import annotations

import pytest

from runtime.api.conftest import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor, set_actor_name
from yoke_core.domain.handlers import reads
from yoke_core.domain.item_owner_label import owner_facts, owner_label

ITEM_ID = 4301


@pytest.mark.parametrize(
    ("stored", "name", "label"),
    [
        ("2", "Ben Bauman", "Ben Bauman (actor id: 2)"),
        ("9", None, "unknown actor (actor id: 9)"),
        ("ben", None, "unknown actor (stored owner: ben)"),
        ("", None, "unassigned"),
        (None, None, "unassigned"),
        ("None", None, "unassigned"),
    ],
)
def test_owner_label_forms(stored, name, label):
    assert owner_label(stored, name) == label


def test_owner_facts_carry_id_name_and_label():
    assert owner_facts("2", {2: "Ben Bauman"}) == {
        "owner_actor_id": 2,
        "owner_name": "Ben Bauman",
        "owner_label": "Ben Bauman (actor id: 2)",
    }
    assert owner_facts("9", {})["owner_name"] is None


def _get_owner(monkeypatch) -> str:
    monkeypatch.setattr(reads, "_read_instructions", lambda *a, **k: [])
    outcome = reads.handle_items_get(
        FunctionCallRequest(
            function="items.get.run",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={"fields": ["owner"]},
        )
    )
    assert outcome.primary_success
    return outcome.result_payload["fields"]["owner"]


def test_items_get_owner_renders_name_and_actor_id(test_db, monkeypatch):
    actor_id = seed_human_actor(test_db)
    set_actor_name(test_db, actor_id, "Ada Operator")
    insert_item(test_db, id=ITEM_ID, title="Owned", owner=str(actor_id))
    test_db.commit()
    assert _get_owner(monkeypatch) == f"Ada Operator (actor id: {actor_id})"


def test_items_get_owner_names_unknown_and_unassigned(test_db, monkeypatch):
    insert_item(test_db, id=ITEM_ID, title="Orphaned", owner="999999")
    test_db.commit()
    assert _get_owner(monkeypatch) == "unknown actor (actor id: 999999)"
    test_db.execute("UPDATE items SET owner = NULL WHERE id = %s", (ITEM_ID,))
    test_db.commit()
    assert _get_owner(monkeypatch) == "unassigned"
