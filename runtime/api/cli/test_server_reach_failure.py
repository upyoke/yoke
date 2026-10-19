"""Connection failures to a Yoke server name what failed and how to check."""

import http.client
import socket
import ssl
import urllib.error
import urllib.request

import pytest

from yoke_cli.config import server_connect
from yoke_cli.config import team_server_authorization as team
from yoke_cli.transport import server_reach_failure as reach
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpBodyError,
    BoundedJsonHttpDeadlineError,
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)
from yoke_contracts.machine_authorization import HostedMachineAuthorizationError

URL = "https://stoodio.example:8688"


def _open_failure(cause: BaseException) -> BoundedJsonHttpError:
    def opener(*_args, **_kwargs):
        raise urllib.error.URLError(cause)

    with pytest.raises(BoundedJsonHttpError) as caught:
        request_json(
            urllib.request.Request(URL + "/v1/health", method="GET"),
            timeout_seconds=5,
            replay_safe=False,
            opener=opener,
        )
    return caught.value


@pytest.mark.parametrize(
    "cause,code",
    [
        (
            socket.gaierror(8, "nodename nor servname provided"),
            reach.SERVER_NAME_UNRESOLVED,
        ),
        (ConnectionRefusedError(61, "Connection refused"), reach.SERVER_REFUSED),
        (TimeoutError("timed out"), reach.SERVER_TIMED_OUT),
        (ssl.SSLError(1, "wrong version number"), reach.SERVER_HTTPS_FAILED),
        (http.client.RemoteDisconnected("closed"), reach.SERVER_NOT_YOKE),
        (OSError(65, "No route to host"), reach.SERVER_UNREACHABLE),
    ],
)
def test_network_failures_are_named_by_cause(cause, code) -> None:
    message = reach.describe(_open_failure(cause), URL, check_server_machine=True)
    assert message is not None
    assert message.startswith(f"{code}: ")
    assert "stoodio.example:8688" in message
    assert "yoke status" in message
    assert "local: reachable here only" in message


@pytest.mark.parametrize(
    "exc",
    [
        BoundedJsonHttpStatusError(404, None),
        BoundedJsonHttpBodyError("JSON response body is not valid JSON"),
        BoundedJsonHttpStatusError(
            401, {"error": {"code": reach.LOCAL_DASHBOARD_ERROR_CODE}}
        ),
    ],
)
def test_an_answer_that_is_not_yoke_is_named(exc) -> None:
    message = reach.describe(exc, URL, check_server_machine=False)
    assert message is not None and message.startswith(f"{reach.SERVER_NOT_YOKE}: ")
    assert "yoke status" not in message


def test_a_local_dashboard_is_named_as_one() -> None:
    exc = BoundedJsonHttpStatusError(
        401, {"error": {"code": reach.LOCAL_DASHBOARD_ERROR_CODE}}
    )
    message = reach.describe(exc, URL, check_server_machine=False)
    assert "local install's dashboard" in (message or "")


def test_other_statuses_stay_with_their_caller() -> None:
    assert (
        reach.describe(
            BoundedJsonHttpStatusError(503, None), URL, check_server_machine=True
        )
        is None
    )


def test_deadline_is_a_timeout() -> None:
    exc = BoundedJsonHttpDeadlineError("JSON request exceeded its time limit")
    message = reach.describe(exc, URL, check_server_machine=False)
    assert (message or "").startswith(f"{reach.SERVER_TIMED_OUT}: ")


def test_team_server_discovery_names_a_refused_server(monkeypatch) -> None:
    def refused(*_args, **_kwargs):
        raise _open_failure(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(team, "request_json", refused)
    with pytest.raises(HostedMachineAuthorizationError) as caught:
        team.sign_in_methods(URL)
    assert str(caught.value).startswith(f"{reach.SERVER_REFUSED}: ")
    assert reach.CHECK_SERVER_MACHINE in str(caught.value)


def test_plain_http_to_another_machine_teaches_the_server_check() -> None:
    with pytest.raises(HostedMachineAuthorizationError) as caught:
        team.sign_in_methods("http://stoodio:8688")
    assert "authorization_origin_invalid" in str(caught.value)
    assert reach.CHECK_SERVER_MACHINE in str(caught.value)
    with pytest.raises(server_connect.ServerConnectError) as connect_caught:
        server_connect.verify_server_health("http://stoodio:8688")
    assert reach.CHECK_SERVER_MACHINE in str(connect_caught.value)


def test_connect_health_names_the_failure(monkeypatch) -> None:
    def refused(*_args, **_kwargs):
        raise _open_failure(socket.gaierror(8, "nodename nor servname provided"))

    monkeypatch.setattr(server_connect, "request_json", refused)
    with pytest.raises(server_connect.ServerConnectError) as caught:
        server_connect.verify_server_health(URL)
    message = str(caught.value)
    assert message.startswith(f"{reach.SERVER_NAME_UNRESOLVED}: ")
    assert reach.CHECK_SERVER_MACHINE in message
    assert "Nothing was persisted" in message


def test_a_loopback_server_skips_the_other_machine_check(monkeypatch) -> None:
    def refused(*_args, **_kwargs):
        raise _open_failure(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(server_connect, "request_json", refused)
    with pytest.raises(server_connect.ServerConnectError) as caught:
        server_connect.verify_server_health("http://127.0.0.1:8765")
    assert str(caught.value).startswith(f"{reach.SERVER_REFUSED}: ")
    assert reach.CHECK_SERVER_MACHINE not in str(caught.value)
