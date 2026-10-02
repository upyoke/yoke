"""Windows GUI lifetime and credential proof never export the desktop password."""

from contextlib import contextmanager
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config.capability_secrets import store_machine_capability_secret
from yoke_harness import desktop_access, windows_desktop_session as desktop
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.ssh_windows_host_operations import SshWindowsHostOperations
from yoke_harness.test_machine_types import HostActionResult

PASSWORD = "private-desktop-test-secret"
SETTINGS = {
    "resource_name": "windows-lab",
    "host": "windows.invalid",
    "user": "Administrator",
    "os": "windows",
    "desktop_route": "ssh-forward",
    "desktop_protocol": "rdp",
    "desktop_port": "3389",
    "desktop_user": "Administrator",
}
LOGIN = {"session_id": 2, "user": "Administrator"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    store_machine_capability_secret(
        "project", "test-machine", "ssh_private_key", "ssh-key"
    )
    store_machine_capability_secret(
        "project", "test-machine:windows-lab", "desktop_password", PASSWORD
    )
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/tools/sdl-freerdp")
    monkeypatch.setattr(desktop_access, "_check_desktop", lambda *args: None)
    return SimpleNamespace(_desktop_project="project", _desktop_settings=SETTINGS)


def test_windows_desktop_access_authenticates_stdin_and_closes_forward(
    setup, monkeypatch, tmp_path, capsys
):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        assert PASSWORD not in repr(argv)
        assert kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    result = desktop_access.open_desktop_access(
        project="project", machine="windows-lab", settings=SETTINGS
    )
    assert result == {
        "user": "Administrator",
        "credential_proof": "authenticated",
        "desktop_session": "not_started",
    }
    auth = next((argv, kw) for argv, kw in calls if "+auth-only" in argv)
    assert auth[1]["input"] == PASSWORD + "\n"
    assert "/from-stdin:force" in auth[0]
    assert not any("/p:" in arg for arg in auth[0])
    assert calls[-1][0][-3:] == ["-O", "exit", "Administrator@windows.invalid"]
    control_path = Path(calls[0][0][calls[0][0].index("-S") + 1])
    assert not control_path.parent.exists()
    assert PASSWORD not in json.dumps(result) + repr(calls[0]) + str(
        capsys.readouterr()
    )
    assert not list(tmp_path.rglob("*.password"))


@pytest.mark.parametrize("failure", ["returncode", "timeout", "oserror"])
def test_failed_authentication_is_named_and_secret_free(setup, monkeypatch, failure):
    @contextmanager
    def forward(*args):
        yield "localhost", 1234, "Administrator"

    def run(argv, **kw):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 30, output=PASSWORD, stderr=PASSWORD)
        if failure == "oserror":
            raise OSError(PASSWORD)
        return subprocess.CompletedProcess(argv, 1, PASSWORD, PASSWORD)

    monkeypatch.setattr(desktop, "desktop_forward", forward)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(
        desktop_access.DesktopAccessError, match="windows_desktop_authentication"
    ) as raised:
        desktop.prove_windows_credentials(
            project="project", machine="windows-lab", settings=SETTINGS
        )
    assert PASSWORD not in str(raised.value)


def test_missing_client_refuses_before_tunnel_or_password_read(setup, monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    monkeypatch.setattr(desktop, "_password", lambda *a: pytest.fail("credential read"))
    monkeypatch.setattr(
        desktop, "desktop_forward", lambda *a: pytest.fail("tunnel opened")
    )
    with pytest.raises(
        desktop_access.DesktopAccessError, match="windows_rdp_client_missing.*human RDP"
    ):
        desktop.prove_windows_credentials(
            project="project", machine="windows-lab", settings=SETTINGS
        )


class PasswordPipe(io.StringIO):
    def close(self):
        self.sent = self.getvalue()
        super().close()


class Client:
    def __init__(self):
        self.stdin = PasswordPipe()
        self.running = True
        self.terminated = False

    def poll(self):
        return None if self.running else 1

    def terminate(self):
        self.terminated = True
        self.running = False

    def wait(self, timeout):
        assert timeout == 5
        return 0


@pytest.mark.parametrize("operation_fails", [False, True])
def test_new_session_keeps_client_and_tunnel_until_operation_finishes(
    setup, monkeypatch, operation_fails
):
    client = Client()
    calls = []
    route_open = []

    @contextmanager
    def forward(*args):
        route_open.append(True)
        try:
            yield "localhost", 1234, "Administrator"
        finally:
            assert client.terminated
            route_open.clear()

    def popen(argv, **kw):
        calls.append((argv, kw))
        assert kw["stdin"] == subprocess.PIPE
        assert kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
        assert PASSWORD not in repr(argv) + repr(kw)
        return client

    sessions = iter([[], [LOGIN]])
    monkeypatch.setattr(
        desktop, "active_windows_sessions", lambda control: next(sessions)
    )
    monkeypatch.setattr(desktop, "desktop_forward", forward)
    monkeypatch.setattr(subprocess, "Popen", popen)
    try:
        with desktop.windows_desktop_session(setup) as evidence:
            assert evidence == {"desktop_session": "started", "windows_session_id": 2}
            assert route_open and not client.terminated
            assert client.stdin.sent == PASSWORD + "\n"
            assert PASSWORD not in json.dumps(evidence)
            if operation_fails:
                raise ValueError("capture failed")
    except ValueError:
        assert operation_fails
    assert client.terminated and not route_open
    assert "+auth-only" not in calls[0][0]


def test_existing_registered_session_reused_without_rdp_client(setup, monkeypatch):
    monkeypatch.setattr(desktop, "active_windows_sessions", lambda control: [LOGIN])
    monkeypatch.setattr(
        desktop, "_client", lambda: pytest.fail("human session disturbed")
    )
    with desktop.windows_desktop_session(setup) as evidence:
        assert evidence["desktop_session"] == "reused"


def test_start_timeout_closes_client_without_credential_diagnostic(setup, monkeypatch):
    client = Client()

    @contextmanager
    def forward(*args):
        yield "localhost", 1234, "Administrator"

    monkeypatch.setattr(desktop, "desktop_forward", forward)
    monkeypatch.setattr(desktop, "active_windows_sessions", lambda control: [])
    monkeypatch.setattr(desktop, "START_TIMEOUT", 0)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: client)
    with pytest.raises(
        desktop_access.DesktopAccessError, match="windows_desktop_start_timeout"
    ) as raised:
        with desktop.windows_desktop_session(setup):
            pytest.fail("unexpected ready session")
    assert client.terminated and PASSWORD not in str(raised.value)


def test_wrong_ssh_user_refuses_before_desktop_probe(setup, monkeypatch):
    setup._desktop_settings = {**SETTINGS, "user": "Other"}
    monkeypatch.setattr(
        desktop, "active_windows_sessions", lambda *a: pytest.fail("probe starts")
    )
    with pytest.raises(
        desktop_access.DesktopAccessError, match="windows_desktop_user_mismatch"
    ):
        with desktop.windows_desktop_session(setup):
            pytest.fail("unexpected session")


def test_foreign_active_login_refuses_before_connecting(setup, monkeypatch):
    monkeypatch.setattr(
        desktop,
        "active_windows_sessions",
        lambda control: [{"session_id": 3, "user": "Human"}],
    )
    monkeypatch.setattr(
        desktop, "_client", lambda: pytest.fail("human session disturbed")
    )
    with pytest.raises(
        desktop_access.DesktopAccessError, match="windows_desktop_user_conflict"
    ):
        with desktop.windows_desktop_session(setup):
            pytest.fail("unexpected session")


def test_screenshot_reports_held_session_and_named_start_failure(setup, monkeypatch):
    @contextmanager
    def session(control):
        yield {"desktop_session": "started", "windows_session_id": 2}

    monkeypatch.setattr(desktop, "windows_desktop_session", session)
    monkeypatch.setattr(
        SshLinuxHostOperations,
        "capture_screenshot",
        lambda self: HostActionResult(True, {"capture_artifact": {"token": "desktop"}}),
    )
    control = SshWindowsHostOperations.__new__(SshWindowsHostOperations)
    result = control.capture_screenshot()
    assert result.ok and result.evidence["desktop_session"] == "started"
    assert result.evidence["capture_artifact"]["token"] == "desktop"

    @contextmanager
    def failed(control):
        raise desktop_access.DesktopAccessError(
            "windows_rdp_client_missing: install FreeRDP"
        )
        yield

    monkeypatch.setattr(desktop, "windows_desktop_session", failed)
    result = control.capture_screenshot()
    assert not result.ok and result.error_code == "windows_rdp_client_missing"
    assert "install FreeRDP" in result.evidence["recovery"]


def test_public_and_qa_controls_keep_registered_desktop_context(setup, monkeypatch):
    from yoke_core.domain.host_control_runner import TestMachineMaterial
    from yoke_core.domain.machine_qa_host_control import host_control_for

    monkeypatch.setattr(
        SshWindowsHostOperations,
        "_host_facts",
        lambda self: {"home": "/home/tester", "shell": "/bin/bash"},
    )
    public = SshWindowsHostOperations.from_contract(
        SimpleNamespace(project="project", settings=SETTINGS)
    )
    qa = host_control_for(
        TestMachineMaterial(
            project_id=1,
            project="project",
            settings=SETTINGS,
            secrets={"ssh_private_key": "ssh-key"},
            secret_paths={"ssh_private_key": "/private/key"},
        )
    )
    for control in (public, qa):
        monkeypatch.setattr(
            desktop,
            "active_windows_sessions",
            lambda observed: (
                [LOGIN]
                if observed._desktop_project == "project"
                and observed._desktop_settings == SETTINGS
                else []
            ),
        )
        monkeypatch.setattr(
            SshLinuxHostOperations,
            "capture_screenshot",
            lambda self: HostActionResult(
                True, {"capture_artifact": {"token": "desktop"}}
            ),
        )
        result = control.capture_screenshot()
        assert result.ok and result.evidence["desktop_session"] == "reused"


@pytest.mark.parametrize("failure", ["returncode", "timeout"])
def test_failed_forward_cleanup_preserves_its_recovery_socket(
    setup, monkeypatch, tmp_path, failure
):
    from yoke_harness import desktop_forward as forward

    directory = tmp_path / "forward-control"
    directory.mkdir()
    monkeypatch.setattr(forward.tempfile, "mkdtemp", lambda **kw: str(directory))

    def run(argv, **kw):
        if "-M" in argv:
            (directory / "ssh").write_text("control-socket-placeholder")
            return subprocess.CompletedProcess(argv, 0)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(forward.subprocess, "run", run)
    with pytest.raises(desktop_access.DesktopAccessError) as error:
        with forward.desktop_forward("project", SETTINGS):
            pass
    assert "desktop_forward_cleanup_failed" in str(error.value)
    assert str(directory / "ssh") in str(error.value)
    assert (directory / "ssh").exists()
