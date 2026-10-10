"""Client-side custody checks for the AWS runner-fleet token broker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json

import pytest

from yoke_cli.transport.https import TransportError
from yoke_cli.transport import runner_fleet_token


def _intent(**overrides):
    authority = {
        "project": "platform",
        "repo": "upyoke/platform",
        "aws_region": "us-east-1",
        "token_broker_function": "yoke-runner-fleet-token-broker",
        **overrides,
    }
    canonical = json.dumps(authority, sort_keys=True, separators=(",", ":"))
    return json.dumps(
        {
            "schema": 1,
            "authority": authority,
            "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        }
    )


class _LambdaClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _response(payload, **metadata):
    return {"Payload": BytesIO(json.dumps(payload).encode()), **metadata}


def test_client_invokes_exact_broker_and_keeps_token_process_only():
    client = _LambdaClient(
        _response(
            {
                "token": "ghs_process_only",
                "expires_at": "2026-07-14T18:30:00Z",
                "repository": "upyoke/platform",
            }
        )
    )
    factory_calls = []

    token = runner_fleet_token.fetch_runner_fleet_token(
        project="platform",
        authority_intent=_intent(),
        aws_env={"AWS_ACCESS_KEY_ID": "test"},
        client_factory=lambda env, region: (
            factory_calls.append((env, region)) or client
        ),
        now=lambda: datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc),
    )

    assert token == "ghs_process_only"
    assert factory_calls == [({"AWS_ACCESS_KEY_ID": "test"}, "us-east-1")]
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["FunctionName"] == "yoke-runner-fleet-token-broker"
    assert call["InvocationType"] == "RequestResponse"
    request = json.loads(call["Payload"])
    assert request["action"] == "provider_token"
    assert request["authority"]["repo"] == "upyoke/platform"
    assert request["authority_sha256"] == json.loads(_intent())["sha256"]
    assert "ghs_process_only" not in call["Payload"].decode()


def test_client_rejects_invalid_authority_digest_before_aws():
    intent = json.loads(_intent())
    intent["authority"]["repo"] = "attacker/repo"
    with pytest.raises(TransportError, match="digest is invalid"):
        runner_fleet_token.fetch_runner_fleet_token(
            project="platform",
            authority_intent=json.dumps(intent),
            aws_env={},
            client_factory=lambda *args: pytest.fail("invoked AWS"),
        )


def test_client_hides_lambda_error_payload():
    secret = "ghs_must_not_escape"
    client = _LambdaClient(
        {
            "FunctionError": "Unhandled",
            "Payload": BytesIO(json.dumps({"errorMessage": secret}).encode()),
        }
    )
    with pytest.raises(TransportError, match="invocation failed") as caught:
        runner_fleet_token.fetch_runner_fleet_token(
            project="platform",
            authority_intent=_intent(),
            aws_env={},
            client_factory=lambda *args: client,
        )
    assert secret not in str(caught.value)


def test_client_rejects_expired_grant():
    client = _LambdaClient(
        _response(
            {
                "token": "ghs_expired",
                "expires_at": "2026-07-14T17:59:59+00:00",
                "repository": "upyoke/platform",
            }
        )
    )
    with pytest.raises(TransportError, match="expired token"):
        runner_fleet_token.fetch_runner_fleet_token(
            project="platform",
            authority_intent=_intent(),
            aws_env={},
            client_factory=lambda *args: client,
            now=lambda: datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("delta,accepted", [(-1, False), (0, False), (1, True)])
def test_grant_expiry_compares_exact_offset_microseconds(delta, accepted):
    now = datetime(2026, 10, 9, 10, 11, 12, 345678, tzinfo=timezone.utc)
    expires = (now + timedelta(microseconds=delta)).astimezone(
        timezone(timedelta(hours=5, minutes=45))
    )
    client = _LambdaClient(
        _response(
            {
                "token": "process-only",
                "expires_at": expires.isoformat(),
                "repository": "upyoke/platform",
            }
        )
    )
    arguments = dict(
        project="platform",
        authority_intent=_intent(),
        aws_env={},
        client_factory=lambda *args: client,
        now=lambda: now,
    )
    if accepted:
        assert (
            runner_fleet_token.fetch_runner_fleet_token(**arguments) == "process-only"
        )
    else:
        with pytest.raises(TransportError, match="expired token"):
            runner_fleet_token.fetch_runner_fleet_token(**arguments)


@pytest.mark.parametrize(
    "value", [None, "", "2026-10-09T10:11:12", "2026-02-30T10:11:12Z", 0]
)
def test_invalid_grant_clock_refuses_without_disclosing_token(value):
    client = _LambdaClient(
        _response(
            {
                "token": "must-stay-private",
                "expires_at": value,
                "repository": "upyoke/platform",
            }
        )
    )
    with pytest.raises(TransportError, match="invalid response") as caught:
        runner_fleet_token.fetch_runner_fleet_token(
            project="platform",
            authority_intent=_intent(),
            aws_env={},
            client_factory=lambda *args: client,
        )
    assert "must-stay-private" not in str(caught.value)


def test_naive_current_clock_refuses_without_disclosing_token():
    client = _LambdaClient(
        _response(
            {
                "token": "must-stay-private",
                "expires_at": "2099-10-09T10:11:12.345678Z",
                "repository": "upyoke/platform",
            }
        )
    )
    with pytest.raises(TransportError, match="current clock is invalid") as caught:
        runner_fleet_token.fetch_runner_fleet_token(
            project="platform",
            authority_intent=_intent(),
            aws_env={},
            client_factory=lambda *args: client,
            now=lambda: datetime(2026, 10, 9),
        )
    assert "must-stay-private" not in str(caught.value)
