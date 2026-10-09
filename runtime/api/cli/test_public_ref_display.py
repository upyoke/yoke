"""Human and JSON receipts share the public response contract."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from yoke_cli.transport.public_ref_display import (
    emit_response,
    prepare_human_response,
    redact_response,
)
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.timestamps import format_instant, parse_instant


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


@pytest.mark.parametrize(
    "clock",
    [
        parse_instant("1969-12-31T23:59:59.123456Z"),
        datetime(
            1970,
            1,
            1,
            5,
            29,
            59,
            123456,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        ),
        None,
    ],
)
@pytest.mark.parametrize("secrets", [(), ("",), ("wire-secret",)])
def test_client_result_clock_image_is_independent_of_redaction(clock, secrets):
    opaque = '{"updated_at":"1970-01-01T05:29:59.123456+05:30"}'
    raw = response().model_copy(
        update={
            "result": {
                "items": [{"id": 99, "created_at": clock}],
                "expires_at": None,
                "token": "wire-secret",
                "body": opaque,
            }
        }
    )
    local = redact_response(raw, secrets)
    expected = raw.model_dump(mode="json")["result"]
    if "wire-secret" in secrets:
        expected["token"] = "<redacted>"
    assert local.result == expected
    assert local.result["items"][0]["created_at"] == (
        format_instant(clock) if clock is not None else None
    )
    assert local.result["expires_at"] is None
    assert local.result["body"] == opaque
    assert local.result["items"][0]["id"] == 99
    assert raw.result["items"][0]["created_at"] is clock
    assert raw.result["token"] == "wire-secret"


@pytest.mark.parametrize("json_mode", [True, False])
@pytest.mark.parametrize("clock", [parse_instant("1969-12-31T23:59:59.123456Z"), None])
def test_output_formats_native_clock_with_null_and_opaque_body(
    capsys, json_mode, clock
):
    opaque = "historical clock text: 1970-01-01T05:29:59.123456+05:30"
    raw = response().model_copy(
        update={"result": {"created_at": clock, "body": opaque}}
    )
    assert emit_response(raw, json_mode=json_mode) == 0
    document = json.loads(capsys.readouterr().out)
    result = document["result"] if json_mode else document
    assert result == {
        "created_at": format_instant(clock) if clock is not None else None,
        "body": opaque,
    }
    assert raw.result["created_at"] is clock
