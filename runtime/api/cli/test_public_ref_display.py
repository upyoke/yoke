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
        if json_mode:
            assert (
                json.loads(output)["result"]
                == prepare_human_response(response()).result
            )
        else:
            assert "public ref: APP-7" in output
            assert "requirement id: 11" in output
            assert "item_id" not in output


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
    output = capsys.readouterr().out
    if json_mode:
        assert json.loads(output)["result"] == {
            "created_at": format_instant(clock) if clock is not None else None,
            "body": opaque,
        }
    else:
        assert (
            f"created at: {format_instant(clock) if clock is not None else 'none'}"
            in output
        )
        assert f"body: {opaque}" in output
    assert raw.result["created_at"] is clock


@pytest.mark.parametrize("json_mode", [True, False])
def test_failed_log_deadline_hint_uses_its_real_parser(monkeypatch, capsys, json_mode):
    from yoke_cli.commands.adapters import github_actions_failed_log as adapter
    from yoke_cli.transport.output_limit import read_output_scope
    from yoke_contracts.api.function_call import FunctionError

    raw = FunctionCallResponse(
        success=False,
        function="github_actions.failed_log",
        version="v1",
        error=FunctionError(
            code="read_deadline_exceeded",
            message="github_actions.failed_log exceeded its 25s server read deadline.",
            recovery_hint="obsolete server advice",
        ),
    )
    monkeypatch.setattr(adapter, "_call", lambda *args, **kwargs: raw)
    args = ["example/repo", "123", "--project", "example"]
    if json_mode:
        args.append("--json")
    with read_output_scope(args, raw.function):
        assert adapter.github_actions_failed_log(args) == 4
    output = capsys.readouterr()
    if json_mode:
        error = json.loads(output.out)["error"]
        assert error["code"] == "read_deadline_exceeded"
        assert error["message"] == raw.error.message
        hint = error["recovery_hint"]
    else:
        assert raw.error.message in output.err
        hint = output.err
    assert "--lines" in hint
    assert "yoke github-actions failed-log --help" in hint
    assert "--limit" not in hint
    assert "--offset" not in hint
    assert "obsolete server advice" not in hint
    assert raw.error.recovery_hint == "obsolete server advice"
