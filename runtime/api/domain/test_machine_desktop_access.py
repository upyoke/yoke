"""Desktop access proves reachability without exposing a login credential."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config.capability_secrets import (
    read_machine_capability_secret,
    store_machine_capability_secret,
)
from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_settings,
)
from yoke_core.domain.handlers import test_machine_desktop as handler
from yoke_harness import desktop_access as desktop


SETTINGS = {
    "resource_name": "lab",
    "host": "lab.example",
    "user": "sshuser",
    "os": "windows",
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
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
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
        {"cloud_instance_id": "invalid"},
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


def test_forward_printable_result_has_no_secret_and_leaves_a_private_copy(
    credentials, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        desktop.subprocess,
        "run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
    )
    probes = []
    monkeypatch.setattr(desktop, "_check_desktop", lambda *args: probes.append(args))
    result = desktop.open_desktop_access(
        project="project", machine="lab", settings=SETTINGS
    )
    path = Path(result["password_file"])
    try:
        assert set(result) == {"address", "user", "password_file"}
        assert PASSWORD not in json.dumps(result) + repr(calls)
        assert path.parent == Path("/tmp")
        assert path.read_text().strip() == PASSWORD
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert result["user"] == "Administrator"
        assert result["address"].startswith("rdp://127.0.0.1:")
        assert probes[0][0] == "127.0.0.1"
        assert "ExitOnForwardFailure=yes" in calls[0]
        assert "IdentitiesOnly=yes" in calls[0]
        assert "-F" in calls[0]
        assert "sshuser@lab.example" == calls[0][-1]
        assert ":[127.0.0.1]:3389" in calls[0][calls[0].index("-L") + 1]
    finally:
        path.unlink()


def test_direct_route_uses_desktop_host_without_starting_ssh(credentials, monkeypatch):
    monkeypatch.setattr(
        desktop.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("direct route starts SSH"),
    )
    probes = []
    monkeypatch.setattr(desktop, "_check_desktop", lambda *args: probes.append(args))
    result = desktop.open_desktop_access(
        project="project",
        machine="lab",
        settings={
            **SETTINGS,
            "desktop_route": "direct",
            "desktop_protocol": "vnc",
            "desktop_host": "desktop.example",
            "desktop_port": "5900",
        },
    )
    try:
        assert result["address"] == "vnc://desktop.example:5900"
        assert probes == [("desktop.example", 5900, "vnc")]
    finally:
        Path(result["password_file"]).unlink()


def test_failed_probe_closes_forward_and_removes_password_copy(
    credentials, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        desktop.subprocess,
        "run",
        lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
    )

    def fail(*args):
        raise OSError(PASSWORD)

    monkeypatch.setattr(desktop, "_check_desktop", fail)
    with pytest.raises(
        desktop.DesktopAccessError, match="desktop_unreachable"
    ) as caught:
        desktop.open_desktop_access(project="project", machine="lab", settings=SETTINGS)
    assert PASSWORD not in str(caught.value)
    control_path = calls[0][calls[0].index("-S") + 1]
    assert not Path(control_path.removesuffix(".ssh")).exists()
    assert calls[-1][-3:] == ["-O", "exit", "sshuser@lab.example"]


def test_missing_password_refuses_before_any_tunnel(credentials, monkeypatch):
    monkeypatch.setattr(
        desktop.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("missing secret starts SSH"),
    )
    with pytest.raises(desktop.DesktopAccessError, match="desktop_password_missing"):
        desktop.open_desktop_access(
            project="project", machine="missing", settings=SETTINGS
        )


def _request():
    return FunctionCallRequest(
        function="test_machine.desktop_access",
        request_id="desktop-test",
        actor={"session_id": "caller"},
        target={"kind": "global"},
        payload={"project": "project", "machine": "lab"},
    )


def test_route_authorization_refuses_foreign_lease_and_returns_only_settings(
    monkeypatch,
):
    detail = {
        "project": "project",
        "machine": "lab",
        "settings": SETTINGS,
        "active_lease": {"session_id": "holder"},
    }
    monkeypatch.setattr(
        handler,
        "handle_get",
        lambda request: HandlerOutcome(primary_success=True, result_payload=detail),
    )
    assert handler.handle_desktop_access(_request()).error.code == "test_machine_leased"
    detail["active_lease"] = {"session_id": "caller"}
    result = handler.handle_desktop_access(_request()).result_payload
    assert set(result) == {"project", "machine", "settings"}


def test_cli_dispatch_never_contains_a_password(credentials, monkeypatch, capsys):
    from yoke_cli.commands.adapters import test_machine_desktop as cli

    calls = []
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        cli, "build_actor", lambda **kw: SimpleNamespace(session_id="caller")
    )
    monkeypatch.setattr(
        cli,
        "call_dispatcher",
        lambda **kw: (
            calls.append(kw)
            or SimpleNamespace(
                success=True,
                result={"project": "project", "machine": "lab", "settings": SETTINGS},
            )
        ),
    )
    monkeypatch.setattr(desktop, "_check_desktop", lambda *args: None)
    monkeypatch.setattr(
        desktop.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0),
    )
    assert (
        cli.test_machine_desktop_access(["--project", "project", "--machine", "lab"])
        == 0
    )
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    try:
        assert calls[0]["payload"] == {"project": "project", "machine": "lab"}
        assert PASSWORD not in captured.out + captured.err + repr(calls)
    finally:
        Path(result["password_file"]).unlink()


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
