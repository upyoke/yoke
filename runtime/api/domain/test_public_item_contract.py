"""Client boundaries carry project-qualified identities without joining ids."""

import pytest
from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.public_item_contract import (
    project_public_identities,
    public_item_request_error,
    public_payload_schema,
)


def request(target=None, payload=None):
    return FunctionCallRequest.model_validate(
        {
            "function": "items.get.run",
            "version": "v1",
            "target": target or {"kind": "global"},
            "actor": {"actor_id": "test", "session_id": ""},
            "payload": payload or {},
        }
    )


@pytest.mark.parametrize(
    "target,payload,code",
    [
        ({"kind": "item", "item_id": 123}, {}, "internal_item_id_forbidden"),
        (
            {"kind": "item", "public_ref": "123", "project_id": "app"},
            {},
            "public_item_ref_required",
        ),
        (
            {"kind": "global"},
            {"rows": [{"item_id": 123}]},
            "internal_item_id_forbidden",
        ),
        (
            {"kind": "global"},
            {"public_refs": ["APP-7", "7"]},
            "public_item_ref_required",
        ),
    ],
)
def test_refuses_internal_keys_and_bare_sequences(target, payload, code):
    assert public_item_request_error(request(target, payload)).code == code


def test_accepts_qualified_refs_and_other_record_ids():
    assert (
        public_item_request_error(
            request(
                {"kind": "epic_task", "public_ref": "APP-7", "task_num": 2},
                {"dependency_public_refs": ["YOK-11"], "plan_id": 9},
            )
        )
        is None
    )


def test_response_projection_preserves_record_ids_and_removes_join_keys():
    source = {
        "item_id": 99,
        "public_ref": "APP-7",
        "run_id": 12,
        "item": {"id": 99, "public_ref": "APP-7", "title": "example"},
        "scope": {"epic_id": 99, "task_num": 2},
        "members": [{"id": 41, "item_id": 99}],
    }
    assert project_public_identities(source, lambda key: {99: "APP-7"}[key]) == {
        "public_ref": "APP-7",
        "run_id": 12,
        "item": {"public_ref": "APP-7", "title": "example"},
        "scope": {"epic_public_ref": "APP-7", "task_num": 2},
        "members": [{"id": 41, "public_ref": "APP-7"}],
    }
    assert source["item_id"] == 99


def test_old_serving_response_needs_no_client_lookup():
    assert project_public_identities(
        {"item_id": 99, "public_ref": "APP-7"}, lambda _: None
    ) == {"public_ref": "APP-7"}
    assert project_public_identities({"current_item_id": 99}, lambda _: None) == {}


def test_schema_teaches_public_refs_and_retains_unrelated_ids():
    class Payload(BaseModel):
        item_id: int
        epic_id: int | None = None
        member_item_ids: list[int]
        plan_id: int

    schema = public_payload_schema(Payload.model_json_schema())
    assert schema["required"] == ["public_ref", "member_public_refs", "plan_id"]
    assert schema["properties"]["public_ref"]["type"] == "string"
    assert schema["properties"]["member_public_refs"]["items"]["type"] == "string"
    assert schema["properties"]["plan_id"]["type"] == "integer"
