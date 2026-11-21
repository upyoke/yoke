"""Viewer failures name the retained client's reason and a reachable repair."""

from contextlib import contextmanager

import pytest

from runtime.api.domain.rdp_desktop_view_test_support import (
    Client,
    PASSWORD,
    SETTINGS,
    RECEIPT,
)
from yoke_harness import rdp_desktop_client as viewer
from yoke_harness.desktop_access import DesktopAccessError


@pytest.fixture
def client_route(monkeypatch):
    monkeypatch.setattr(viewer.shutil, "which", lambda _: "/tools/sdl-freerdp")

    @contextmanager
    def forward(*args):
        yield "127.0.0.1", 5555, "fixture"

    monkeypatch.setattr(viewer, "desktop_forward", forward)


def test_missing_executable_teaches_install(monkeypatch):
    monkeypatch.setattr(viewer.shutil, "which", lambda _: None)
    with pytest.raises(
        DesktopAccessError, match="desktop_rdp_client_missing:.*Install FreeRDP"
    ):
        viewer.view_desktop("project", "lab", SETTINGS, PASSWORD, RECEIPT)


@pytest.mark.parametrize(
    "reason,recovery",
    [
        ("ERRINFO_LOGOFF_BY_USER", "/var/log/xrdp-sesman.log"),
        ("ERRCONNECT_CONNECT_FAILED", "registered desktop port"),
        ("ERRCONNECT_LOGON_FAILURE", "desktop_password fixture secret"),
        ("ERRINFO_SERVER_DENIED_CONNECTION", "retained client log"),
        ("client_exit_unknown", "retained client log"),
    ],
)
def test_present_client_failure_names_log_reason(
    client_route, monkeypatch, reason, recovery
):
    process = Client(code=2, output=reason + "\n" + PASSWORD)
    process.stdin.close = lambda: None
    monkeypatch.setattr(viewer.subprocess, "Popen", lambda *a, **kw: process)
    with pytest.raises(DesktopAccessError) as refused:
        viewer.view_desktop("project", "lab", SETTINGS, PASSWORD, RECEIPT)
    message = str(refused.value)
    assert reason in message and recovery in message and "retained log:" in message
    assert "Install FreeRDP" not in message and PASSWORD not in message


@pytest.mark.parametrize(
    "error,reason",
    [
        (PermissionError("denied"), "desktop_view_unavailable"),
        (FileNotFoundError("gone"), "desktop_rdp_client_missing"),
    ],
)
def test_launch_error_distinguishes_missing_from_permissions(
    client_route, monkeypatch, error, reason
):
    def launch(*a, **kw):
        raise error

    monkeypatch.setattr(viewer.subprocess, "Popen", launch)
    with pytest.raises(
        DesktopAccessError, match=reason + ":.*retained log:"
    ) as refused:
        viewer.view_desktop("project", "lab", SETTINGS, PASSWORD, RECEIPT)
    assert ("Install FreeRDP" in str(refused.value)) == isinstance(
        error, FileNotFoundError
    )


def test_direct_route_pins_the_certificate_first_seen(client_route, monkeypatch):
    from yoke_harness import rdp_certificate_pin

    process = Client()
    process.stdin.close = lambda: None
    pinned = "ab" * 32
    monkeypatch.setattr(
        rdp_certificate_pin, "pinned_certificate", lambda *a, **kw: pinned
    )

    def launch(argv, **kw):
        assert f"/cert:fingerprint:sha256:{pinned}" in argv
        assert "/cert:ignore" not in argv and "/cert:deny" not in argv
        return process

    monkeypatch.setattr(viewer.subprocess, "Popen", launch)
    viewer.view_desktop(
        "project",
        "lab",
        {**SETTINGS, "desktop_route": "direct"},
        PASSWORD,
        RECEIPT,
        )
