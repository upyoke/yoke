"""Delivery points obey scope, live workflow buckets, and atomic validation."""

import pytest
from pydantic import ValidationError

from yoke_core.domain import workflow_execution_instructions as domain
from yoke_core.domain import db_helpers
from yoke_core.domain.execution_instruction_delivery import InstructionDelivery
from yoke_core.domain.handlers import (
    workflow_execution_instructions_crud as crud,
    reads,
    lifecycle_transition,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.item_page_reads_test_support import _connection
from runtime.api.test_workflow_execution_instruction_functions import (
    _UnclosableConnection,
    _request,
    _capture_events,
)


@pytest.fixture
def conn(monkeypatch):
    connection = _UnclosableConnection(_connection())
    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: connection)
    _capture_events(monkeypatch)
    return connection


def seed(conn, content, **delivery):
    identifier = domain.create_instruction(conn, content=content, delivery=delivery)
    domain.set_instruction_scope(
        conn,
        identifier,
        workflow_ids=["dash"],
        applies_to_all_projects=True,
        project_ids=[],
    )
    conn.commit()
    return identifier


def ids(rows):
    return [row["id"] for row in rows]


def test_creation_read_and_stage_delivery_are_distinct(conn):
    creation = seed(conn, "Authoring rule", on_every_read=False)
    reading = seed(conn, "Reader rule", before_creation=False)
    entering = seed(
        conn,
        "Implementation rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["implementing"],
    )
    assert ids(
        domain.resolve_execution_instructions(conn, workflow_id="dash", project_id=7)
    ) == [creation]
    assert ids(domain.resolve_for_item(conn, 51)) == [reading]
    conn.execute("UPDATE items SET status = 'implementing' WHERE id = 51")
    assert ids(domain.resolve_for_item(conn, 51)) == [reading, entering]
    assert ids(
        domain.resolve_for_item(conn, 51, delivery_point="when_entering_stage")
    ) == [entering]
    conn.execute("UPDATE items SET status = 'reviewing-implementation' WHERE id = 51")
    assert ids(domain.resolve_for_item(conn, 51)) == [reading]
    assert ids(domain.item_instruction_descriptors(conn, 51)) == [creation]


def test_claim_receipt_delivers_full_applicable_item_instructions(conn, monkeypatch):
    from yoke_core.domain.handlers import claims_work
    from yoke_core.domain import sessions_lifecycle_claim

    reading = seed(conn, "Reader rule", before_creation=False)
    monkeypatch.setattr(claims_work, "_connect_rw", lambda: conn)
    monkeypatch.setattr(sessions_lifecycle_claim, "claim_work", lambda *a, **k: {
        "id": 1, "session_id": "worker", "target_kind": "item", "scope": {"item_id": 51},
    })
    outcome = claims_work.handle_acquire(FunctionCallRequest(
        function="claims.work.acquire", actor=ActorContext(actor_id="2", session_id="worker"),
        target=TargetRef(kind="item", item_id=51), payload={"target": {"kind": "item"}},
    ))
    assert ids(outcome.result_payload["execution_instructions"]) == [reading]
    assert outcome.result_payload["execution_instructions"][0]["content"] == "Reader rule"


def test_bucket_matching_uses_the_pinned_definition(conn):
    import json
    from yoke_core.domain.workflow_registry import definition_digest

    row = conn.execute("SELECT id, definition_json FROM workflow_versions").fetchone()
    definition = json.loads(row[1])
    definition["stages"][1]["id"] = "authoring-code"
    definition["transitions"][0]["to_stage_id"] = "authoring-code"
    definition["transitions"][1]["from_stage_id"] = "authoring-code"
    conn.execute(
        "UPDATE workflow_versions SET definition_json = ?, definition_digest = ? WHERE id = ?",
        (json.dumps(definition), definition_digest(definition), row[0]),
    )
    entering = seed(
        conn,
        "Bucket rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["implementing"],
    )
    conn.execute("UPDATE items SET status = 'authoring-code' WHERE id = 51")
    assert ids(domain.resolve_for_item(conn, 51)) == [entering]
    # Exceptional and terminal states do not accidentally inherit a previous bucket.
    for status in ("blocked", "cancelled", "done"):
        conn.execute("UPDATE items SET status = ? WHERE id = 51", (status,))
        assert domain.resolve_for_item(conn, 51) == []


@pytest.mark.parametrize(
    "delivery, reason",
    [
        ({"before_creation": False, "on_every_read": False}, "delivery_point_required"),
        ({"when_entering_stage": True}, "stage_bucket_required"),
        ({"stage_buckets": ["not-a-bucket"]}, "Input should be"),
    ],
)
def test_invalid_delivery_refuses_before_creating_a_row(conn, delivery, reason):
    outcome = crud.handle_instruction_create(
        _request(
            "workflow.execution_instruction.create", {"content": "Rule", **delivery}
        )
    )
    assert not outcome.primary_success
    assert reason in outcome.error.message
    assert domain.list_instructions(conn) == []


def test_partial_update_and_scope_edits_preserve_omitted_delivery(conn):
    instruction = seed(
        conn,
        "Rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["reviewing"],
    )
    updated = crud.handle_instruction_update(
        _request(
            "workflow.execution_instruction.update",
            {
                "instruction_id": instruction,
                "content": "New prose",
                "on_every_read": True,
            },
        )
    )
    assert updated.primary_success
    scoped = crud.handle_instruction_set_scope(
        _request(
            "workflow.execution_instruction.set_scope",
            {
                "instruction_id": instruction,
                "workflow_ids": ["issue"],
                "applies_to_all_projects": True,
                "stage_buckets": ["release"],
            },
        )
    )
    assert scoped.primary_success
    row = domain.list_instructions(conn)[0]
    assert row["before_creation"] is False
    assert row["on_every_read"] is True
    assert row["when_entering_stage"] is True
    assert row["stage_buckets"] == ["release"]
    assert row["content"] == "New prose"


def test_invalid_scope_edit_preserves_prose_bindings_and_delivery(conn):
    instruction = seed(
        conn,
        "Rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["reviewing"],
    )
    prior = domain.list_instructions(conn)
    outcome = crud.handle_instruction_set_scope(
        _request(
            "workflow.execution_instruction.set_scope",
            {
                "instruction_id": instruction,
                "workflow_ids": ["issue"],
                "stage_buckets": [],
            },
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "delivery_invalid"
    assert domain.list_instructions(conn) == prior
    with pytest.raises(ValidationError):
        domain.update_instruction(
            conn,
            instruction,
            content="Changed",
            delivery={"when_entering_stage": False},
        )
    assert domain.list_instructions(conn) == prior


def test_existing_defaults_and_duplicate_targets(conn):
    seed(conn, "Existing behavior")
    row = domain.list_instructions(conn)[0]
    assert (
        row["before_creation"],
        row["on_every_read"],
        row["when_entering_stage"],
        row["stage_buckets"],
    ) == (True, True, False, [])
    assert InstructionDelivery(stage_buckets=["idea", "idea"]).stage_buckets == ["idea"]


def test_scalar_and_section_reads_attach_live_bucket_instructions(conn, monkeypatch):
    entering = seed(
        conn,
        "Stage rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["reviewing"],
    )
    monkeypatch.setattr(
        "yoke_core.domain.items_queries.query_item", lambda *_a: "## Scope\nText\n"
    )
    request = FunctionCallRequest(
        function="items.get.run",
        target=TargetRef(kind="item", item_id=51),
        actor=ActorContext(session_id="test"),
        payload={"fields": ["status"]},
    )
    assert ids(
        reads.handle_items_get(request).result_payload["execution_instructions"]
    ) == [entering]
    request.payload = {"fields": ["spec"], "section": "Scope"}
    assert ids(
        reads.handle_items_get(request).result_payload["execution_instructions"]
    ) == [entering]


def test_transition_returns_only_entered_bucket_instructions_and_not_on_failure(
    conn, monkeypatch
):
    seed(conn, "Every read rule")
    entering = seed(
        conn,
        "Stage rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["implementing"],
    )
    monkeypatch.setattr(
        lifecycle_transition, "_read_current_status", lambda *_a: ("idea", "TEST")
    )
    monkeypatch.setattr(lifecycle_transition, "_frozen_blocked", lambda *_a: None)

    def update(**kwargs):
        conn.execute(
            "UPDATE items SET status = ? WHERE id = ?",
            (kwargs["value"], kwargs["item_id"]),
        )
        return {"success": True}

    monkeypatch.setattr("yoke_core.domain.backlog.execute_update", update)
    request = FunctionCallRequest(
        function="lifecycle.transition.execute",
        actor=ActorContext(session_id="test"),
        target=TargetRef(kind="item", item_id=51),
        payload={"target_status": "implementing"},
    )
    outcome = lifecycle_transition.handle_transition(request)
    assert outcome.primary_success
    assert ids(outcome.result_payload["execution_instructions"]) == [entering]
    monkeypatch.setattr(
        "yoke_core.domain.backlog.execute_update",
        lambda **_k: {"success": False, "error": "refused"},
    )
    assert not lifecycle_transition.handle_transition(request).primary_success


def test_resolve_projection_keeps_the_delivery_selection_in_its_full_read(conn):
    entering = seed(
        conn,
        "Stage rule",
        before_creation=False,
        on_every_read=False,
        when_entering_stage=True,
        stage_buckets=["release"],
    )
    outcome = crud.handle_instruction_resolve(
        _request(
            "workflow.execution_instruction.resolve",
            {
                "workflow": "dash",
                "project": "acme",
                "delivery_point": "when_entering_stage",
                "stage_bucket": "release",
            },
        )
    )
    assert ids(outcome.result_payload["execution_instructions"]) == [entering]
    assert (
        "--delivery-point when_entering_stage --stage-bucket release --full"
        in outcome.result_payload["execution_instructions"][0]["read"]
    )
