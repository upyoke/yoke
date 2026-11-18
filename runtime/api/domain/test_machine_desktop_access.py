"""Desktop access proves reachability without exposing a login credential."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.capability_secret_store import (
    read_machine_capability_secret,
    store_machine_capability_secret,
)
from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_settings,
)
from yoke_contracts.owner_private_path import is_owner_private_file
from yoke_core.domain.handlers import machine_desktop_access as handler
from yoke_harness import desktop_access as desktop

pytestmark = pytest.mark.windows

SETTINGS = {
    "resource_name": "lab",
    "host": "lab.example",
    "user": "sshuser",
    "os": "macos",
    "operating_notes": "",
    "desktop_route": "ssh-forward",
    "desktop_protocol": "rdp",
    "desktop_port": "3389",
    "desktop_user": "Administrator",
}
PASSWORD = "a-test-desktop-secret"

@pytest.fixture
def credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    store_machine_capability_secret(
        "project", "test-machine", "ssh_private_key", "fake-key"
    )
    store_machine_capability_secret(
        "project", "test-machine:lab", "desktop_password", PASSWORD
    )
    return tmp_path

def test_passwords_are_machine_owned_and_private(credentials):
    path = store_machine_capability_secret(
        "project", "test-machine:other", "desktop_password", "other-secret"
    )
    assert is_owner_private_file(path)
    assert (
        read_machine_capability_secret(
            "project", "test-machine:lab", "desktop_password"
        )
        == PASSWORD
    )
    assert (
        read_machine_capability_secret(
            "project", "test-machine:other", "desktop_password"
        )
        == "other-secret"
    )

@pytest.mark.parametrize(
    "change",
    [
        {"desktop_route": "invalid"},
        {"desktop_protocol": "invalid"},
        {"desktop_port": "65536"},
        {"desktop_port": "0"},
        {"desktop_host": "bad host"},
        {"desktop_user": "unsafe;user"},
        {"desktop_password": PASSWORD},
        {"cloud_instance_id": "bad instance"},
    ],
)
def test_registration_rejects_invalid_routes_and_password_settings(change):
    with pytest.raises(TestMachineCapabilityError):
        validate_test_machine_settings({**SETTINGS, **change})

def test_registration_requires_complete_route_and_keeps_cloud_identity():
    with pytest.raises(TestMachineCapabilityError, match="desktop_route_incomplete"):
        validate_test_machine_settings(
            {key: value for key, value in SETTINGS.items() if key != "desktop_port"}
        )
    result = validate_test_machine_settings(
        {**SETTINGS, "cloud_instance_id": "i-07b658cc018669344"}
    )
    assert result["cloud_instance_id"] == "i-07b658cc018669344"
    assert result["desktop_user"] == "Administrator"


def _request():
    return FunctionCallRequest(
        function="test_machine.desktop_access",
        request_id="desktop-test",
        actor={"session_id": "caller"},
        target={"kind": "global"},
        payload={"project": "project", "test_machine": "lab"},
    )

def test_route_authorization_refuses_foreign_lease_and_returns_only_settings(
    monkeypatch,
):
    detail = {
        "project": "project",
        "test_machine": "lab",
        "settings": SETTINGS,
        "active_lease": {"session_id": "holder"},
    }
    monkeypatch.setattr(
        handler,
        "handle_get",
        lambda request: HandlerOutcome(primary_success=True, result_payload=detail),
    )
    from types import SimpleNamespace
    from yoke_core.domain.sessions_analytics_core import SessionError

    def no_seat(conn, **kwargs):
        raise SessionError("steering_seat_required", "requires a live steering seat")

    monkeypatch.setattr(
        handler.db_helpers, "connect", lambda: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(handler, "resolve_project_id", lambda conn, project: 1)
    monkeypatch.setattr(handler, "require_operator_seat", no_seat)
    refused = handler.handle_desktop_access(_request())
    assert refused.error.code == "steering_seat_required"
    detail["active_lease"] = {"session_id": "caller"}
    result = handler.handle_desktop_access(_request()).result_payload
    assert set(result) == {"project", "test_machine", "settings"}


@pytest.mark.parametrize(
    "protocol,fragments",
    [
        ("rdp", [b"\x03", b"\x00\x00", b"\x13"]),
        ("vnc", [b"R", b"FB", b" "]),
    ],
)
def test_protocol_probe_handles_fragmented_handshakes(monkeypatch, protocol, fragments):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def recv(self, count):
            return fragments.pop(0)

        def sendall(self, data):
            assert data.startswith(b"\x03\x00")

    monkeypatch.setattr(
        desktop.socket, "create_connection", lambda *a, **kw: Connection()
    )
    desktop._check_desktop("localhost", 10000, protocol)
    assert not fragments

def test_desktop_secret_literal_is_rejected_before_dispatch(monkeypatch, capsys):
    from yoke_cli.commands.adapters import projects_secret

    monkeypatch.setattr(
        projects_secret, "dispatch_and_emit", lambda **kw: pytest.fail("secret relayed")
    )
    result = projects_secret.projects_capability_secret_set(
        [
            "--project",
            "project",
            "--cap-type",
            "test-machine:lab",
            "--key",
            "desktop_password",
            PASSWORD,
        ]
    )
    assert result != 0
    assert PASSWORD not in capsys.readouterr().err

def test_debug_secret_read_cannot_print_desktop_password(monkeypatch, capsys):
    from yoke_core.domain import projects_capability_secrets_command as cli

    monkeypatch.setattr(
        cli, "cmd_capability_get_secret", lambda *a: pytest.fail("read secret")
    )
    assert (
        cli.run_capability_secret_command(
            SimpleNamespace(
                command="capability-get-secret",
                key="desktop_password",
                project="project",
                type="test-machine:lab",
            )
        )
        == 1
    )
    result = capsys.readouterr()
    assert not result.out
    assert "desktop_password_not_printable" in result.err
