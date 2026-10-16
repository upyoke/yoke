"""A held desktop viewer closes its client and SSH forward on request."""

from contextlib import contextmanager
import io
import subprocess

from yoke_harness import rdp_desktop_client as viewer

PASSWORD = "fixture-secret"
SETTINGS = {
    "resource_name": "lab",
    "os": "linux",
    "host": "host.example",
    "user": "fixture",
    "desktop_route": "ssh-forward",
    "desktop_protocol": "rdp",
    "desktop_port": "3389",
    "desktop_user": "fixture",
}
RECEIPT = {"desktop_session": "reused", "environment": {"DISPLAY": ":10.0"}}


class Client:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("client started\n")
        self.running = True
        self.terminated = False
        self.returncode = None

    def poll(self):
        return None if self.running else 0

    def wait(self, timeout=None):
        self.running = False
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True


def test_held_view_stays_open_until_close(monkeypatch):
    events = []
    process = Client()
    monkeypatch.setattr(viewer.shutil, "which", lambda name: "/tools/sdl-freerdp")
    monkeypatch.setattr(viewer.sys, "platform", "linux")

    @contextmanager
    def forward(project, settings):
        events.append("forward-open")
        try:
            yield "127.0.0.1", 5555, "fixture"
        finally:
            events.append("forward-close")

    def popen(argv, **kwargs):
        events.append("client")
        assert "/from-stdin:force" in argv
        assert PASSWORD not in repr(argv)
        return process

    monkeypatch.setattr(viewer, "desktop_forward", forward)
    monkeypatch.setattr(viewer.subprocess, "Popen", popen)

    def geometry(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, "  Width: 1280\n  Height: 800\n  Depth: 24\n", ""
        )

    opened = viewer.DesktopView.open(
        "project", "lab", SETTINGS, PASSWORD, RECEIPT, geometry
    )
    assert events == ["forward-open", "client"]
    assert process.terminated is False
    opened.close()
    assert process.terminated is True
    assert events[-1] == "forward-close"
