"""Adding a dependency edge that already exists updates it and reports truthfully."""

from __future__ import annotations

import pytest

from runtime.api.conftest import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import item_dependency_writes
from yoke_core.domain.item_dependency import (
    cmd_dependency_add,
    cmd_dependency_update,
)


@pytest.fixture
def items(test_db):
    insert_item(test_db, id=5, title="blocker")
    insert_item(test_db, id=10, title="dependent")
    return test_db


def _stored(conn):
    rows = conn.execute(
        "SELECT id, source, satisfaction, rationale, evidence_json "
        "FROM item_dependencies"
    ).fetchall()
    assert len(rows) == 1
    return tuple(rows[0])


def _handler_add(payload: dict):
    return item_dependency_writes.handle_item_dependency_add(
        FunctionCallRequest(
            function="items.dependency.add",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=10),
            payload={"blocking_item": "YOK-5", **payload},
        )
    )


def test_new_edge_reports_created(items):
    write = cmd_dependency_add(
        items,
        "YOK-10",
        "YOK-5",
        "shepherd",
        rationale="first",
        evidence_json='{"a": 1}',
    )
    dep_id, source, satisfaction, rationale, evidence = _stored(items)
    assert write.action == "created"
    assert write.message == f"created dependency #{dep_id}"
    assert (source, satisfaction, rationale, evidence) == (
        "shepherd",
        "status:done",
        "first",
        '{"a": 1}',
    )


def test_duplicate_add_updates_source_and_rationale_in_place(items):
    created = cmd_dependency_add(
        items, "YOK-10", "YOK-5", "shepherd", rationale="old reason"
    )
    write = cmd_dependency_add(items, "YOK-10", "YOK-5", "dash", rationale="new reason")
    dep_id, source, _, rationale, _ = _stored(items)
    assert dep_id == created.edge.dependency_id
    assert (source, rationale) == ("dash", "new reason")
    assert write.action == "updated"
    assert write.message == (
        f"updated existing dependency #{dep_id}: "
        "source shepherd -> dash; rationale old reason -> new reason"
    )


def test_duplicate_add_updates_satisfaction_and_evidence(items):
    cmd_dependency_add(items, "YOK-10", "YOK-5", "operator", rationale="r")
    write = cmd_dependency_add(
        items,
        "YOK-10",
        "YOK-5",
        "operator",
        satisfaction="fact:merged",
        rationale="r",
        evidence_json='{"b": 2}',
    )
    _, _, satisfaction, _, evidence = _stored(items)
    assert (satisfaction, evidence) == ("fact:merged", '{"b": 2}')
    assert [field for field, _, _ in write.changes] == ["satisfaction", "evidence_json"]


def test_identical_duplicate_add_reports_unchanged(items):
    first = cmd_dependency_add(items, "YOK-10", "YOK-5", "operator", rationale="r")
    before = _stored(items)
    write = cmd_dependency_add(items, "YOK-10", "YOK-5", "operator", rationale="r")
    assert _stored(items) == before
    assert write.action == "unchanged"
    assert (
        write.message == f"unchanged: existing dependency #{first.edge.dependency_id}"
    )


def test_omitted_satisfaction_and_evidence_keep_stored_values(items):
    cmd_dependency_add(
        items,
        "YOK-10",
        "YOK-5",
        "operator",
        satisfaction="fact:merged",
        rationale="r",
        evidence_json='{"keep": true}',
    )
    write = cmd_dependency_add(items, "YOK-10", "YOK-5", "dash", rationale="r")
    _, source, satisfaction, _, evidence = _stored(items)
    assert (source, satisfaction, evidence) == ("dash", "fact:merged", '{"keep": true}')
    assert [field for field, _, _ in write.changes] == ["source"]


def test_handler_reply_reports_stored_row_not_request_echo(items):
    created = _handler_add(
        {"source": "shepherd", "satisfaction": "fact:merged", "rationale": "first"}
    )
    again = _handler_add({"source": "dash", "rationale": "second"})
    dep_id, source, satisfaction, rationale, evidence = _stored(items)
    assert again.primary_success
    reply = again.result_payload
    assert created.result_payload["dependency_id"] == dep_id
    assert reply["dependency_id"] == dep_id
    assert reply["action"] == "updated"
    assert (reply["source"], reply["satisfaction"], reply["rationale"]) == (
        source,
        satisfaction,
        rationale,
    )
    assert reply["satisfaction"] == "fact:merged"  # request omitted it
    assert reply["evidence_json"] == evidence
    assert reply["result"].startswith(f"updated existing dependency #{dep_id}: ")


def test_update_changes_source_and_evidence(items):
    cmd_dependency_add(items, "YOK-10", "YOK-5", "shepherd", rationale="r")
    cmd_dependency_update(
        items, "YOK-10", "YOK-5", source="dash", evidence_json='{"c": 3}'
    )
    _, source, _, _, evidence = _stored(items)
    assert (source, evidence) == ("dash", '{"c": 3}')


def test_update_refuses_unknown_source(items):
    cmd_dependency_add(items, "YOK-10", "YOK-5", "shepherd", rationale="r")
    with pytest.raises(ValueError, match="source must be"):
        cmd_dependency_update(items, "YOK-10", "YOK-5", source="bogus")
    assert _stored(items)[1] == "shepherd"


def test_update_with_no_field_names_every_option(items):
    cmd_dependency_add(items, "YOK-10", "YOK-5", "shepherd", rationale="r")
    with pytest.raises(ValueError, match="--source, --evidence"):
        cmd_dependency_update(items, "YOK-10", "YOK-5")
