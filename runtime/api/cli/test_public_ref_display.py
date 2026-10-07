"""Human and JSON receipts share the public response contract."""

import json

import pytest

from yoke_cli.transport.public_ref_display import (
    emit_response,
    prepare_human_response,
    redact_response,
)
from yoke_contracts.api.function_call import FunctionCallResponse


def response():
    return FunctionCallResponse(
        success=True,
        function="items.get.run",
        version="v1",
        result={
            "item_id": 99,
            "public_ref": "APP-7",
            "requirement_id": 11,
            "nested": {"owner_item_id": 99},
        },
    )


def test_old_server_receipt_omits_unavailable_optional_refs():
    assert prepare_human_response(response()).result == {
        "public_ref": "APP-7",
        "requirement_id": 11,
        "nested": {},
    }


def test_json_and_human_output_do_not_leak_internal_keys(capsys):
    for json_mode in (True, False):
        assert emit_response(response(), json_mode=json_mode) == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        result = parsed["result"] if json_mode else parsed
        assert result == prepare_human_response(response()).result


def test_transport_redacts_secrets_without_projecting_machine_responses():
    raw = response().model_copy(
        update={"result": {"items": [{"id": 99}], "token": "secret"}}
    )
    redacted = redact_response(raw, ("secret",))
    assert redacted.result == {"items": [{"id": 99}], "token": "<redacted>"}
    assert raw.result["token"] == "secret"
    assert prepare_human_response(redacted).result == {
        "items": [{}],
        "token": "<redacted>",
    }


@pytest.mark.parametrize("adapter", ["doctor", "readiness"])
def test_specialized_json_output_filters_older_server_item_ids(capsys, adapter):
    from yoke_cli.commands.adapters.doctor_output import emit_doctor_response
    from yoke_cli.commands.adapters.readiness import _emit_prd_validate

    emit = emit_doctor_response if adapter == "doctor" else _emit_prd_validate
    emit(response(), json_mode=True)
    assert (
        json.loads(capsys.readouterr().out)["result"]
        == prepare_human_response(response()).result
    )
