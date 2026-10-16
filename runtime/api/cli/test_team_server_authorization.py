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
    monkeypatch.setattr(auth.platform, "system", lambda: "Linux")
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
    assert requests[0][1] == {
        "machine_id": MACHINE_ID,
        "machine_name": "My laptop",
        "platform": "Linux",
    }
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
    for payload, expected in (
        # A server predating company_sign_in offered device codes only with it.
        ({"device_code": True}, team.SignInMethods(True, True)),
        (
            {"device_code": True, "company_sign_in": False},
            team.SignInMethods(True, False),
        ),
    ):
        monkeypatch.setattr(
            team,
            "request_json",
            lambda *a, _p=payload, **k: BoundedJsonHttpResponse(
                payload=_p, status=200, headers={}
            ),
        )
        assert team.sign_in_methods(ORIGIN) == expected
    monkeypatch.setattr(
        team,
        "request_json",
        lambda *a, **k: BoundedJsonHttpResponse(payload={}, status=200, headers={}),
    )
    with pytest.raises(
        auth.HostedMachineAuthorizationError, match="machine_sign_in_contract_invalid"
    ):
        team.browser_sign_in_available(ORIGIN)


@pytest.mark.parametrize("company_sign_in", [True, False])
def test_connect_starts_machine_approval_for_self_host(monkeypatch, company_sign_in):
    monkeypatch.setattr(
        team,
        "sign_in_methods",
        lambda url: team.SignInMethods(url == ORIGIN, company_sign_in),
    )
    seen = []
    monkeypatch.setattr(
        command, "_connect_hosted", lambda parsed: seen.append(parsed) or 0
    )
    assert command.connect([ORIGIN]) == 0
    assert seen[0].self_host is True


def test_server_without_machine_approval_keeps_explicit_token_path(monkeypatch, capsys):
    monkeypatch.setattr(
        team, "sign_in_methods", lambda _: team.SignInMethods(False, False)
    )
    assert command.connect([ORIGIN]) == 2
    assert "--token-stdin" in capsys.readouterr().err


def test_team_tui_routes_company_sign_in_or_admission_choices(monkeypatch, tmp_path):
    from yoke_cli.config.onboard_wizard_flow_team_server import TeamServerConnectFlow
    from yoke_cli.config.onboard_wizard_view_helpers import ViewHelpers

    class Shell(TeamServerConnectFlow, ViewHelpers):
        result = argparse.Namespace(api_url="", config_path=tmp_path / "config.json")

        def _goto(self, view):
            self.view = view

        def _run_checking(self, **kwargs):
            self.success = kwargs["on_success"]

        def _start_hosted_machine_authorization(self):
            self.selected = "browser"

        def _goto_server_connection_form(self):
            self.selected = "token"

        def _step_back(self):
            self.selected = "back"

    shell = Shell()
    shell._discover_team_server(ORIGIN)
    shell.success(True)
    assert shell.selected == "browser"
    assert shell._machine_authorization_server == ORIGIN
    shell.success(False)
    assert [row.label for row in shell.view.prompt.choices] == [
        "This is my own machine",
        "Enter invite code",
        "Use an API token",
        "Back",
    ]
    shell.view.on_select("own")
    assert shell.selected == "browser" and shell._machine_authorization_server == ORIGIN
    shell.view.on_select("token")
    assert shell.selected == "token"
    assert shell._machine_authorization_server is None
    shell.view.on_select("back")
    assert shell.selected == "back"


def test_local_notice_and_private_invite_back_preserve_config(monkeypatch, tmp_path):
    import asyncio
    from runtime.api.cli.onboard_wizard_test_helpers import make_app, stub_path_doctor
    from yoke_cli.config import local_reachability
    from yoke_cli.config.onboard_wizard import WizardDefaults

    stub_path_doctor(monkeypatch)
    config = tmp_path / "config.json"
    config.write_text('{"settings":{"preserved":true}}')
    before = config.read_bytes()
    monkeypatch.setattr(
        local_reachability,
        "active_connection_is_local",
        lambda path: path == str(config),
    )
    app, _ = make_app(WizardDefaults(config_path=str(config), api_url=ORIGIN))

    async def scenario():
        async with app.run_test() as pilot:
            app._goto_team_server()
            assert (
                local_reachability.LOCAL_REACHABILITY_NOTICE
                in app._history[-1].prompt.subtitle
            )
            assert "yoke self-host init" in app._history[-1].prompt.subtitle
            app._discover_team_server(ORIGIN)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app._history[-1].prompt.key == "connect.machine_admission"
            app._after_machine_admission("invite")
            await pilot.pause()
            prompt = app._history[-1].prompt
            assert prompt.input.password and not prompt.input.allow_placeholder
            assert "ask an admin to run `yoke invite <name>`" in prompt.subtitle
            await pilot.press("escape")
            assert app._history[-1].prompt.key == "connect.machine_admission"
            app._after_machine_admission("back")
            assert app._history[-1].prompt.key == "connect.team_server_url"
            assert config.read_bytes() == before

    asyncio.run(scenario())


@pytest.mark.parametrize("refused", [False, True])
def test_invite_choice_uses_teammate_identity_and_private_persistence(
    monkeypatch, tmp_path, refused
):
    from yoke_cli.config import onboard_wizard_flow_machine_admission as admission
    from yoke_cli.config.onboard_wizard_flow_team_server import TeamServerConnectFlow
    from yoke_cli.config.onboard_wizard_view_helpers import ViewHelpers
    from runtime.api.fixtures.machine_config_test import select_machine_config_file

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"schema_version": 1, "machine_id": MACHINE_ID}))
    select_machine_config_file(monkeypatch, config)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    before = config.read_bytes()
    code, token = "yinv_private", "invited-machine-token"
    calls = []

    def request(req, **kwargs):
        calls.append(json.loads(req.data))
        if refused:
            raise BoundedJsonHttpStatusError(409, {"error": "invite_consumed"})
        return BoundedJsonHttpResponse(
            {"api_url": ORIGIN, "org": "team", "token": token}, 200, {}
        )

    monkeypatch.setattr(admission.teammate_invite_redemption, "request_json", request)
    verification = {"ok": True, "actor": {"label": "Invited teammate"}}
    monkeypatch.setattr(
        admission.yoke_token_verify,
        "verify",
        lambda url, value: (
            verification if value == token else pytest.fail("wrong credential")
        ),
    )

    class Shell(TeamServerConnectFlow, ViewHelpers):
        result = argparse.Namespace(api_url=ORIGIN, config_path=config)

        def _goto(self, view):
            self.view = view

        def _run_checking(self, **kwargs):
            try:
                value = kwargs["work"]()
            except auth.HostedMachineAuthorizationError as exc:
                kwargs["on_error"](exc)
            else:
                kwargs["on_success"](value)

        def _goto_yoke_verify_success(self, result):
            self.connected = result

    shell = Shell()
    shell._after_machine_admission("invite")
    shell.view.on_select(code)
    assert calls[0]["invite_code"] == code and calls[0]["machine_id"] == MACHINE_ID
    if refused:
        assert "invite_consumed" in shell.view.prompt.message
        assert (
            "reissue" in shell.view.prompt.message
            and code not in shell.view.prompt.message
        )
        assert config.read_bytes() == before
    else:
        from pathlib import Path

        secret = Path(shell.result.token_file)
        assert shell.connected["actor"]["label"] == "Invited teammate"
        assert shell.result.token is None and secret.read_text().strip() == token
        assert secret.stat().st_mode & 0o777 == 0o600
        assert code not in config.read_text() and token not in config.read_text()


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
