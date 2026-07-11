"""Client-side custody checks for the hosted runner-fleet token broker."""

from __future__ import annotations

import json

import pytest

from yoke_cli.transport.https import HttpsConnection, TransportError
from yoke_cli.transport import runner_fleet_token


class _Response:
    def __init__(self, payload, *, cache_control="no-store"):
        self.payload = payload
        self.headers = {"Cache-Control": cache_control}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.payload[:size]


class _Opener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


def _intent():
    return json.dumps(
        {
            "schema": 1,
            "authority": {"repo": "upyoke/platform"},
            "sha256": "a" * 64,
        }
    )


def test_client_posts_digest_and_keeps_token_process_only(monkeypatch):
    response = _Response(
        json.dumps(
            {
                "token": "ghs_process_only",
                "expires_at": "2026-07-10T12:30:00+00:00",
                "repository": "upyoke/platform",
            }
        ).encode()
    )
    opener = _Opener(response)
    monkeypatch.setattr(runner_fleet_token, "_OPENER", opener)
    connection = HttpsConnection(
        api_url="https://api.upyoke.com",
        token="yoke_infrastructure_token",
    )

    token = runner_fleet_token.fetch_runner_fleet_token(
        connection,
        project="platform",
        authority_intent=_intent(),
    )

    assert token == "ghs_process_only"
    request, timeout = opener.requests[0]
    assert request.full_url == (
        "https://api.upyoke.com/v1/projects/platform/runner-fleet-token"
    )
    assert request.get_header("Authorization") == ("Bearer yoke_infrastructure_token")
    assert json.loads(request.data)["authority_sha256"] == "a" * 64
    assert 0 < timeout <= 30.0


def test_client_rejects_cacheable_token_response(monkeypatch):
    opener = _Opener(_Response(b"{}", cache_control="public, max-age=60"))
    monkeypatch.setattr(runner_fleet_token, "_OPENER", opener)

    with pytest.raises(TransportError, match="not marked no-store"):
        runner_fleet_token.fetch_runner_fleet_token(
            HttpsConnection("https://api.upyoke.com", "token"),
            project="platform",
            authority_intent=_intent(),
        )
