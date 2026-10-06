"""Shared device-code client handles team servers without changing Cloud wire."""

import argparse
import json
import pytest
from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.config import team_server_authorization as team
from yoke_cli.commands import connect as command
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpResponse,
    BoundedJsonHttpStatusError,
)
from yoke_contracts.machine_authorization import APPROVAL_PAGE_PATH

ORIGIN = "https://team.example"
MACHINE_ID = "c37ab111-0a67-4b50-8b4a-72463f9e5dd3"


def test_shared_client_sends_identity_and_accepts_self_host_authority(monkeypatch):
    monkeypatch.setattr(
        auth.machine_config_mutation,
        "ensure_local_machine_identity",
        lambda: MACHINE_ID,
    )
    monkeypatch.setattr(auth, "machine_display_name", lambda: "My laptop")
    responses = [
        {
            "device_code": "secret",
            "user_code": "ABCDE-12345",
            "expires_in": 600,
            "interval": 2,
            "verification_uri": ORIGIN + APPROVAL_PAGE_PATH,
            "verification_uri_complete": ORIGIN + APPROVAL_PAGE_PATH + "/ABCDE-12345",
        },
        {"api_url": ORIGIN, "org": "team", "token": "machine-token"},
    ]
    requests = []

    def request(req, **kwargs):
        requests.append((req.full_url, json.loads(req.data), kwargs))
        return BoundedJsonHttpResponse(payload=responses.pop(0), status=200, headers={})

    monkeypatch.setattr(auth, "request_json", request)
    pending = auth.start(ORIGIN, self_host=True)
    credential = auth.complete(pending, sleep=lambda _: None, monotonic=lambda: 0)
    assert credential.api_url == ORIGIN
    assert requests[0][1] == {"machine_id": MACHINE_ID, "machine_name": "My laptop"}
    assert requests[1][1]["device_code"] == "secret"
    assert requests[1][2]["sensitive_values"] == ("secret",)


def test_team_server_method_detection_is_explicit(monkeypatch):
    monkeypatch.setattr(
        team,
        "request_json",
        lambda *a, **k: BoundedJsonHttpResponse(
            payload={"device_code": False}, status=200, headers={}
        ),
    )
    assert team.browser_sign_in_available(ORIGIN) is False
    monkeypatch.setattr(
        team,
        "request_json",
        lambda *a, **k: BoundedJsonHttpResponse(payload={}, status=200, headers={}),
    )
    with pytest.raises(
        auth.HostedMachineAuthorizationError, match="machine_sign_in_contract_invalid"
    ):
        team.browser_sign_in_available(ORIGIN)


def test_connect_selects_company_sign_in_for_self_host(monkeypatch):
    monkeypatch.setattr(team, "browser_sign_in_available", lambda url: url == ORIGIN)
    seen = []
    monkeypatch.setattr(
        command, "_connect_hosted", lambda parsed: seen.append(parsed) or 0
    )
    assert command.connect([ORIGIN]) == 0
    assert seen[0].self_host is True


def test_unconfigured_server_keeps_explicit_token_path(monkeypatch, capsys):
    monkeypatch.setattr(team, "browser_sign_in_available", lambda _: False)
    assert command.connect([ORIGIN]) == 2
    assert "--token-stdin" in capsys.readouterr().err


def test_team_tui_routes_browser_or_token_after_server_discovery():
    from yoke_cli.config.onboard_wizard_flow_team_server import TeamServerConnectFlow

    class Shell(TeamServerConnectFlow):
        result = argparse.Namespace(api_url="")

        def _run_checking(self, **kwargs):
            self.success = kwargs["on_success"]

        def _start_hosted_machine_authorization(self):
            self.selected = "browser"

        def _goto_server_connection_form(self):
            self.selected = "token"

    shell = Shell()
    shell._discover_team_server(ORIGIN)
    shell.success(True)
    assert shell.selected == "browser"
    assert shell._machine_authorization_server == ORIGIN
    shell.success(False)
    assert shell.selected == "token"
    assert shell._machine_authorization_server is None


@pytest.mark.parametrize(
    "reason",
    [
        "authorization_start_rate_limited",
        "authorization_client_capacity",
        "authorization_capacity",
    ],
)
def test_client_teaches_named_start_admission_refusals(monkeypatch, reason):
    monkeypatch.setattr(
        auth,
        "_machine_identity",
        lambda: {"machine_id": MACHINE_ID, "machine_name": "laptop"},
    )

    def refused(*args, **kwargs):
        raise BoundedJsonHttpStatusError(429, {"error": reason})

    monkeypatch.setattr(auth, "request_json", refused)
    with pytest.raises(
        auth.HostedMachineAuthorizationError, match=reason + ": finish pending"
    ):
        auth.start(ORIGIN, self_host=True)


@pytest.mark.parametrize(
    "reason", ["authorization_client_capacity", "authorization_capacity"]
)
def test_client_stops_polling_with_named_capacity_refusal(monkeypatch, reason):
    monkeypatch.setattr(
        auth,
        "_machine_identity",
        lambda: {"machine_id": MACHINE_ID, "machine_name": "laptop"},
    )
    seen = []

    def refused(*args, **kwargs):
        seen.append(True)
        raise BoundedJsonHttpStatusError(429, {"error": reason})

    monkeypatch.setattr(auth, "request_json", refused)
    pending = auth.PendingMachineAuthorization(
        ORIGIN,
        "secret",
        "code",
        ORIGIN + APPROVAL_PAGE_PATH,
        ORIGIN + APPROVAL_PAGE_PATH,
        600,
        2,
        True,
    )
    with pytest.raises(
        auth.HostedMachineAuthorizationError,
        match=reason + ": finish pending",
    ):
        auth.complete(pending, sleep=lambda _: None, monotonic=lambda: 0)
    assert seen == [True]
