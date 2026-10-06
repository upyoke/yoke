"""The published machine sign-in schema and CLI agree on every wire outcome."""

import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from yoke_contracts import machine_authorization as wire
from yoke_contracts.machine_authorization_schema import SCHEMA_RESOURCE, schema_text
from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.transport.bounded_json_http import BoundedJsonHttpResponse

ORIGIN = "https://team.example"
APPROVED = {"token": "private-token", "org": "team", "api_url": ORIGIN}


def test_published_schema_matches_models_and_is_valid():
    actual = files("yoke_contracts").joinpath(SCHEMA_RESOURCE).read_text()
    assert actual == schema_text(), (
        "regenerate machine_authorization_schema and commit it"
    )
    Draft202012Validator.check_schema(json.loads(actual))


@pytest.mark.parametrize("error", wire.POLL_OUTCOMES)
def test_cli_parses_every_published_poll_outcome(monkeypatch, error):
    schema = json.loads(files("yoke_contracts").joinpath(SCHEMA_RESOURCE).read_text())
    outcome = schema["x-http"]["poll"]["outcomes"][error]
    body = {"error": error}
    Draft202012Validator({**schema, "$ref": f"#/$defs/{outcome['body']}"}).validate(
        body
    )
    assert (
        wire.parse_authorization_response(
            body, outcome["status"], operation="poll"
        ).error
        == error
    )
    answers = iter(
        [
            BoundedJsonHttpResponse(body, outcome["status"], {"Retry-After": "7"}),
            BoundedJsonHttpResponse(APPROVED, 200, {}),
        ]
    )
    monkeypatch.setattr(auth, "request_json", lambda *a, **k: next(answers))
    monkeypatch.setattr(
        auth,
        "_machine_identity",
        lambda: {"machine_id": "machine", "machine_name": "host"},
    )
    pending = wire.PendingMachineAuthorization(
        ORIGIN,
        "secret",
        "CODE",
        ORIGIN + "/machine-approval",
        ORIGIN + "/machine-approval/CODE",
        60,
        2,
        self_host=True,
    )
    now = [0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    if outcome["retryable"]:
        result = auth.complete(pending, sleep=sleep, monotonic=lambda: now[0])
        assert result.token == APPROVED["token"]
        assert waits == ([2, 7] if outcome["status"] == 429 else [2, 2])
    else:
        error_type = (
            wire.HostedMachineAuthorizationDenied
            if error == "authorization_denied"
            else wire.HostedMachineAuthorizationError
        )
        with pytest.raises(
            error_type, match=error.removeprefix("authorization_").replace("_", " ")
        ):
            auth.complete(pending, sleep=sleep, monotonic=lambda: now[0])


@pytest.mark.parametrize(
    "body,status",
    [
        ({"error": "authorization_pending"}, 200),
        ({"error": "authorization_pending"}, 503),
        ({"token": "private-token", "org": "team"}, 200),
        ({**APPROVED, "unexpected": True}, 200),
    ],
)
def test_invalid_response_refuses_without_disclosing_secrets(body, status):
    with pytest.raises(
        wire.HostedMachineAuthorizationError,
        match="authorization_response_invalid.*reconnect",
    ) as exc:
        wire.parse_authorization_response(body, status, operation="poll")
    assert "private-token" not in str(exc.value)


@pytest.mark.parametrize(
    "field,value", [("interval", True), ("expires_in", 59), ("device_code", " ")]
)
def test_start_schema_rejects_invalid_values(field, value):
    body = dict(
        device_code="secret",
        user_code="CODE",
        verification_uri=ORIGIN + "/connect",
        verification_uri_complete=ORIGIN + "/connect?code=CODE",
        expires_in=600,
        interval=2,
    )
    body[field] = value
    with pytest.raises(
        wire.HostedMachineAuthorizationError, match="authorization_response_invalid"
    ):
        wire.parse_authorization_response(body, 200, operation="start")
