"""`yoke connect` treats the public upyoke.com site as the hosted app."""

import pytest

from yoke_cli.commands import connect as command
from yoke_cli.config import team_server_authorization as team
from yoke_cli.transport import server_reach_failure as reach
from yoke_contracts.api_urls import HOSTED_PLATFORM_URL
from yoke_contracts.bounded_json_http import BoundedJsonHttpStatusError
from yoke_contracts.machine_authorization import HostedMachineAuthorizationError


@pytest.mark.parametrize(
    "url",
    [
        "https://upyoke.com",
        "https://upyoke.com/",
        "https://www.upyoke.com",
        "HTTPS://WWW.UpYoke.com/",
        HOSTED_PLATFORM_URL,
    ],
)
def test_public_site_starts_the_hosted_approval_flow(monkeypatch, url):
    monkeypatch.setattr(
        team,
        "sign_in_methods",
        lambda _: pytest.fail("hosted connect must not run self-host discovery"),
    )
    seen = []
    monkeypatch.setattr(
        command, "_connect_hosted", lambda parsed: seen.append(parsed) or 0
    )
    assert command.connect([url]) == 0
    assert seen[0].self_host is False
    assert seen[0].url == HOSTED_PLATFORM_URL


def test_other_upyoke_hosts_stay_self_hosted(monkeypatch):
    monkeypatch.setattr(
        team, "sign_in_methods", lambda _: team.SignInMethods(True, True)
    )
    seen = []
    monkeypatch.setattr(
        command, "_connect_hosted", lambda parsed: seen.append(parsed) or 0
    )
    assert command.connect(["https://docs.upyoke.com"]) == 0
    assert seen[0].self_host is True


def test_html_405_from_discovery_names_a_website_not_an_operator(monkeypatch, capsys):
    def website(*_args, **_kwargs):
        # A non-JSON body decodes to no payload.
        raise BoundedJsonHttpStatusError(405, None)

    monkeypatch.setattr(team, "request_json", website)
    with pytest.raises(HostedMachineAuthorizationError) as caught:
        team.sign_in_methods("https://example.com")
    message = str(caught.value)
    assert message.startswith(f"{reach.SERVER_NOT_YOKE}: example.com ")
    assert "HTTP 405" in message
    assert HOSTED_PLATFORM_URL in message
    assert "operator" not in message
    assert command.connect(["https://example.com"]) == 1
    err = capsys.readouterr().err
    assert reach.SERVER_NOT_YOKE in err and HOSTED_PLATFORM_URL in err


def test_json_405_from_a_yoke_server_keeps_the_operator_recovery(monkeypatch):
    def refused(*_args, **_kwargs):
        raise BoundedJsonHttpStatusError(405, {"error": "method_not_allowed"})

    monkeypatch.setattr(team, "request_json", refused)
    with pytest.raises(
        HostedMachineAuthorizationError, match="machine_sign_in_unavailable: .*HTTP 405"
    ):
        team.sign_in_methods("https://team.example")
