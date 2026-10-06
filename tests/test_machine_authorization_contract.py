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


# Bodies from Platform's token route: recovery is detail, not message.
@pytest.mark.parametrize(
    "status,body",
    [
        (
            503,
            {
                "error": "machine_credential_unavailable",
                "detail": "The universe could not answer; retry the approved code.",
            },
        ),
        (
            409,
            {
                "error": "machine_credential_refused",
                "detail": "This machine is retired; ask its owner to restore it.",
            },
        ),
        (
            400,
            {
                "error": "machine_identity_required",
                "detail": "Send machine_id as this machine's canonical UUID. A credential is bound to one machine, so it cannot be issued without one.",
            },
        ),
        (413, {"error": "payload_too_large"}),
        (400, {"error": "invalid_request"}),
        (410, {"error": "authorization_missing"}),
    ],
)
@pytest.mark.parametrize("http_error", [False, True])
def test_live_cloud_refusals_validate_and_keep_cli_recovery(
    monkeypatch, status, body, http_error
):
    from yoke_cli.transport.bounded_json_http import BoundedJsonHttpStatusError

    schema = json.loads(files("yoke_contracts").joinpath(SCHEMA_RESOURCE).read_text())
    model = (
        "MachineAuthorizationUnavailable"
        if status == 503
        else "MachineAuthorizationRefused"
    )
    Draft202012Validator({**schema, "$ref": f"#/$defs/{model}"}).validate(body)
    response = wire.parse_authorization_response(body, status, operation="poll")
    assert response.recovery_text == body.get("detail", "")
    pending = wire.PendingMachineAuthorization(
        "https://app.upyoke.com",
        "same-device-secret",
        "CODE",
        "https://app.upyoke.com/connect",
        "https://app.upyoke.com/connect?user_code=CODE",
        60,
        2,
    )
    approved = {
        "token": "private-token",
        "org": "team",
        "api_url": "https://app.upyoke.com/api/orgs/team",
    }
    answers = iter([body, approved])
    seen = []

    def post_json(url, payload, **kwargs):
        seen.append(payload)
        answer = next(answers)
        if answer is body and http_error:
            raise BoundedJsonHttpStatusError(status, answer)
        return answer, status if answer is body else 200, {}

    monkeypatch.setattr(auth, "_post_json", post_json)
    monkeypatch.setattr(
        auth,
        "_machine_identity",
        lambda: {"machine_id": "machine", "machine_name": "host"},
    )
    clock = [0]

    def sleep(seconds):
        clock[0] += seconds

    if status == 503:
        credential = auth.complete(pending, sleep=sleep, monotonic=lambda: clock[0])
        assert credential.token == approved["token"]
        assert len(seen) == 2
        assert seen[0] == seen[1]
    else:
        with pytest.raises(wire.HostedMachineAuthorizationError) as exc:
            auth.complete(pending, sleep=sleep, monotonic=lambda: clock[0])
        assert body["error"] in str(exc.value)
        if "detail" in body:
            assert body["detail"] in str(exc.value)
        assert "authorization_response_invalid" not in str(exc.value)
        assert len(seen) == 1


@pytest.mark.parametrize("operation", ["start", "poll"])
def test_response_type_refusals_survive_optimized_python(operation):
    import subprocess
    import sys

    script = """
from yoke_cli.config import hosted_machine_authorization as auth
from yoke_contracts import machine_authorization as wire
auth._post_json = lambda *a, **k: ({}, 200, {})
auth._machine_identity = lambda: {"machine_id": "machine", "machine_name": "host"}
auth.parse_authorization_response = lambda *a, **k: wire.MachineAuthorizationRefused(error="unexpected_outcome")
try:
    if OPERATION == "start":
        auth.start("https://app.upyoke.com")
    else:
        pending = wire.PendingMachineAuthorization("https://app.upyoke.com", "secret", "CODE", "", "", 60, 2)
        auth.complete(pending, sleep=lambda seconds: None, monotonic=lambda: 0)
except wire.HostedMachineAuthorizationError as exc:
    print(str(exc))
else:
    raise SystemExit("missing named refusal")
""".replace("OPERATION", repr(operation))
    result = subprocess.run(
        [sys.executable, "-O", "-c", script], text=True, capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "authorization_response_invalid" in result.stdout
    assert "reconnect" in result.stdout
