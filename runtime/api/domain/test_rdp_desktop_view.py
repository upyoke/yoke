"""Visible XFCE viewing keeps fixture credentials private and owns cleanup."""

import base64
from contextlib import contextmanager
import io
import json
import subprocess

import pytest

from yoke_cli.config.capability_secrets import store_machine_capability_secret
from yoke_harness import desktop_access, rdp_desktop_client as viewer

PASSWORD = "fixture-secret"
SETTINGS = {
    "resource_name": "lab",
    "os": "windows",
    "host": "host.example",
    "user": "Administrator",
    "desktop_route": "ssh-forward",
    "desktop_protocol": "rdp",
    "desktop_port": "3390",
    "desktop_user": "fixture",
}
RECEIPT = {"desktop_session": "reused", "environment": {"DISPLAY": ":10.0"}}


class Client:
    def __init__(self, *, interrupted=False):
        self.stdin = io.StringIO()
        self.password = None
        self.running = True
        self.interrupted = interrupted
        self.terminated = False

    def poll(self):
        return None if self.running else 0

    def wait(self, timeout=None):
        if self.interrupted and timeout is None:
            raise KeyboardInterrupt()
        self.running = False
        return 0

    def terminate(self):
        self.terminated = True


def geometry(command, **kw):
    assert "DISPLAY=:10.0" in command and "xwininfo -root" in command
    return subprocess.CompletedProcess(
        command, 0, "  Width: 1280\n  Height: 1024\n  Depth: 24\n", ""
    )


@pytest.mark.parametrize("interrupted", [False, True])
def test_view_uses_actual_geometry_stdin_and_always_closes_forward(
    monkeypatch, interrupted
):
    events = []
    process = Client(interrupted=interrupted)
    # Retain the received bytes while allowing the product to close stdin.
    stream = process.stdin
    stream.close = lambda: events.append(("password", stream.getvalue()))
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setattr(viewer.shutil, "which", lambda name: "/tools/sdl-freerdp")

    @contextmanager
    def forward(project, settings):
        events.append("forward-open")
        try:
            yield "127.0.0.1", 5555, "fixture"
        finally:
            events.append("forward-close")

    def popen(argv, **kw):
        events.append(("client", argv, kw))
        assert PASSWORD not in repr(argv) + repr(kw)
        assert "/from-stdin:force" in argv
        assert "/size:1280x1024" in argv and "/bpp:24" in argv
        assert "/u:fixture" in argv and "/v:127.0.0.1:5555" in argv
        assert "SDL_VIDEODRIVER" not in kw["env"]
        assert kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
        return process

    monkeypatch.setattr(viewer, "desktop_forward", forward)
    monkeypatch.setattr(viewer.subprocess, "Popen", popen)
    result = viewer.view_desktop(
        "project", "lab", SETTINGS, PASSWORD, RECEIPT, geometry
    )
    assert result == {
        "user": "fixture",
        "desktop_session": "reused",
        "display": ":10.0",
        "viewer": "closed",
    }
    assert ("password", PASSWORD + "\n") in events
    assert events[-1] == "forward-close"
    assert process.terminated is interrupted
    assert PASSWORD not in json.dumps(result)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "Width: 0\nHeight: 1024\nDepth: 24\n",
        "Width: 1280\nHeight: 1024\nDepth: 8\n",
    ],
)
def test_geometry_refusal_happens_before_connect(monkeypatch, output):
    monkeypatch.setattr(viewer.shutil, "which", lambda name: "/tools/sdl-freerdp")
    monkeypatch.setattr(
        viewer, "desktop_forward", lambda *a: pytest.fail("invalid geometry connects")
    )
    with pytest.raises(
        desktop_access.DesktopAccessError, match="desktop_view_geometry"
    ):
        viewer.view_desktop(
            "project",
            "lab",
            SETTINGS,
            PASSWORD,
            RECEIPT,
            lambda *a, **kw: subprocess.CompletedProcess([], 0, output, ""),
        )


def test_missing_client_refuses_before_host_or_forward(monkeypatch):
    monkeypatch.setattr(viewer.shutil, "which", lambda name: None)
    with pytest.raises(
        desktop_access.DesktopAccessError, match="desktop_rdp_client_missing"
    ):
        viewer.view_desktop(
            "project",
            "lab",
            SETTINGS,
            PASSWORD,
            RECEIPT,
            lambda *a, **kw: pytest.fail("host called"),
        )


@pytest.mark.parametrize("os_name", ["linux", "windows"])
def test_prepare_uses_registered_xfce_user_port_and_wsl_stdin_frame(
    tmp_path, monkeypatch, os_name
):
    calls = []
    settings = {**SETTINGS, "os": os_name}

    def run(argv, **kw):
        calls.append((argv, kw))
        command = argv[-1]
        supplied = kw["input"]
        if os_name == "windows":
            assert command.startswith("powershell.exe -NoLogo")
            command, supplied = supplied.split("\n", 1)
            command = base64.b64decode(command).decode()
        if command == "id -un":
            return subprocess.CompletedProcess(argv, 0, "fixture\n", "")
        assert command.endswith(" 3390")
        assert supplied == PASSWORD + "\n"
        assert PASSWORD not in repr(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(RECEIPT), "")

    monkeypatch.setattr(desktop_access.subprocess, "run", run)
    receipt, _ = desktop_access._prepare_desktop(settings, tmp_path / "key", PASSWORD)
    assert receipt == RECEIPT
    assert len(calls) == 2


def test_wrong_default_wsl_user_refuses_before_desktop_login(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        desktop_access.subprocess,
        "run",
        lambda argv, **kw: (
            calls.append(argv)
            or subprocess.CompletedProcess(argv, 0, "different-user\n", "")
        ),
    )
    with pytest.raises(
        desktop_access.DesktopAccessError, match="desktop_user_mismatch"
    ):
        desktop_access._prepare_desktop(SETTINGS, tmp_path / "key", PASSWORD)
    assert len(calls) == 1


def test_view_path_does_not_materialize_password_file(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    store_machine_capability_secret(
        "project", "test-machine", "ssh_private_key", "test-key"
    )
    store_machine_capability_secret(
        "project", "test-machine:lab", "desktop_password", PASSWORD
    )
    monkeypatch.setattr(
        desktop_access, "_prepare_desktop", lambda *a: (RECEIPT, geometry)
    )
    monkeypatch.setattr(
        desktop_access.tempfile,
        "mkstemp",
        lambda **kw: pytest.fail("password file created"),
    )
    calls = []
    monkeypatch.setattr(
        viewer, "view_desktop", lambda *a: calls.append(a) or {"viewer": "closed"}
    )
    assert desktop_access.open_desktop_access(
        project="project", machine="lab", settings=SETTINGS, view=True
    ) == {"viewer": "closed"}
    assert calls[0][3] == PASSWORD
