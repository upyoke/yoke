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


@pytest.mark.parametrize("item", ["42", "invalid", True, -1])
def test_engine_target_rejects_untyped_identity_before_reading(monkeypatch, item):
    from yoke_core.domain import control_plane_transport
    from yoke_core.domain.public_item_target import public_item_target

    def unavailable(_connect):
        raise AssertionError("invalid identity must not open a connection")

    monkeypatch.setattr(
        control_plane_transport, "local_connection_or_none", unavailable
    )
    with pytest.raises(ValueError, match="public_item_ref_required"):
        public_item_target(item)


def test_artifact_selector_refuses_bare_number_before_connection(monkeypatch):
    from yoke_core.domain import machine_config, qa_cli_parser, yok_n_parser

    monkeypatch.setattr(machine_config, "project_id", lambda *_: "yoke")
    monkeypatch.setattr(
        yok_n_parser, "connect", lambda: pytest.fail("numeric selector opened a DB")
    )
    with pytest.raises(SystemExit) as refused:
        qa_cli_parser.build_parser().parse_args(["artifact-list", "--item-id", "42"])
    assert refused.value.code == 2


def test_response_projection_preserves_numbered_task_maps():
    from yoke_core.domain.function_response_refs import collect_item_ids

    result = {"epic_id": 99, "cascade_updated": {2: "1", 3: ""}}
    assert collect_item_ids(result) == {99}
    assert project_public_identities(result, lambda _: "APP-7") == {
        "epic_public_ref": "APP-7",
        "cascade_updated": {2: "1", 3: ""},
    }


def test_dotted_setting_paths_are_not_item_identity_fields():
    assignments = {
        "release.fleet_rehearsal.primary.entry.0057_shepherd_public_refs": "receipt",
        "settings.current_item_id": 99,
    }
    payload = {"assignments": assignments}
    assert public_item_request_error(request(payload=payload)) is None
    assert project_public_identities(payload, lambda _: "APP-7") == payload


def test_missing_progress_log_names_the_public_item(test_db, monkeypatch):
    from runtime.api.conftest import insert_item
    from yoke_core.domain import sections
    from yoke_core.domain.handlers import items_progress_log

    insert_item(test_db, id=901, project_sequence=7)
    monkeypatch.setattr(sections, "get_section", lambda *_: None)
    outcome = items_progress_log.handle_get(request({"kind": "item", "item_id": 901}))
    assert outcome.error.code == "not_found"
    assert "YOK-7" in outcome.error.message
    assert "901" not in outcome.error.message


@pytest.mark.parametrize("member", [901, None])
def test_failed_correction_notice_teaches_a_public_member_or_run_scope(
    test_db, monkeypatch, member
):
    from runtime.api.conftest import insert_item
    from yoke_core.domain import (
        db_helpers,
        deployment_qa_correction_notice,
        qa_requirement_replacement,
    )
    from yoke_core.domain.handlers.qa_requirement_supersede import (
        handle_qa_requirement_supersede,
    )

    insert_item(test_db, id=901, project_sequence=7)
    monkeypatch.setattr(db_helpers, "connect", lambda: test_db)
    monkeypatch.setattr(
        qa_requirement_replacement,
        "declare_existing_replacement",
        lambda *_, **kwargs: {
            "deployment_run_id": "example-run",
            "deployment_stage": "qa",
            "deployment_member_item_id": member,
        },
    )

    def unavailable(*_, **kwargs):
        raise RuntimeError("wake unavailable")

    monkeypatch.setattr(
        deployment_qa_correction_notice, "notify_correction", unavailable
    )
    outcome = handle_qa_requirement_supersede(
        request(
            {"kind": "qa_requirement", "qa_requirement_id": 11},
            {
                "declare_replacement": True,
                "superseded_by_requirement_id": 12,
                "rationale": "corrected case",
            },
        )
    )
    assert outcome.primary_success
    recovery = outcome.result_payload["correction_notice"]["recovery"]
    assert "901" not in recovery
    assert ("--member YOK-7" in recovery) == (member is not None)
    assert ("--member" in recovery) == (member is not None)
