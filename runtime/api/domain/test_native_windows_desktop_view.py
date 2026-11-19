"""Native Windows --view opens FreeRDP on the host's own RDP listener."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from yoke_contracts.machine_config.capability_secret_store import (
    store_test_machine_secret,
)
from yoke_harness import desktop_access, rdp_certificate_pin, rdp_desktop_client as viewer

from runtime.api.domain.rdp_desktop_view_test_support import Client, PASSWORD

SETTINGS = {
    "resource_name": "windows-native-lab",
    "os": "windows",
    "host": "windows-native-lab.tail.ts.net",
    "user": "yokeqa",
    "desktop_route": "direct",
    "desktop_protocol": "rdp",
    "desktop_port": "3389",
    "desktop_user": "winnative\\yokeqa",
}
FINGERPRINT = "ab" * 32


@pytest.fixture
def launched(tmp_path, monkeypatch):
    """Record the FreeRDP argv and stdin; forbid any SSH run or geometry probe."""
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    store_test_machine_secret("windows-native-lab", "desktop_password", PASSWORD)
    state = {"pins": [], "forward": []}
    monkeypatch.setattr(viewer.shutil, "which", lambda name: "/tools/sdl-freerdp")
    monkeypatch.setattr(
        rdp_certificate_pin,
        "pinned_certificate",
        lambda host, port, error, yoke_home: state["pins"].append((host, port))
        or FINGERPRINT,
    )
    for module in (desktop_access.subprocess, viewer.subprocess):
        monkeypatch.setattr(
            module, "run", lambda *a, **kw: pytest.fail(f"remote command ran: {a}")
        )
    monkeypatch.setattr(
        desktop_access, "_prepare_desktop", lambda *a: pytest.fail("XFCE prepared")
    )
    mkstemp = desktop_access.tempfile.mkstemp

    def no_password_file(**kw):
        assert kw.get("suffix") != ".password", "password file created"
        return mkstemp(**kw)

    monkeypatch.setattr(desktop_access.tempfile, "mkstemp", no_password_file)

    @contextmanager
    def forward(project, settings):
        state["forward"].append("open")
        if settings["desktop_route"] == "ssh-forward":
            yield "127.0.0.1", 49152, settings["desktop_user"]
        else:
            yield settings["host"], int(settings["desktop_port"]), settings["desktop_user"]
        state["forward"].append("close")

    def popen(argv, **kw):
        state["argv"] = argv
        process = Client()
        stream = process.stdin
        stream.close = lambda: state.setdefault("stdin", stream.getvalue())
        state["kw"] = kw
        return process

    monkeypatch.setattr(viewer, "desktop_forward", forward)
    monkeypatch.setattr(viewer.subprocess, "Popen", popen)
    return state


def _view(settings):
    announced = []
    desktop_access.open_desktop_access(
        project="yoke",
        test_machine="windows-native-lab",
        settings=settings,
        announce=announced.append,
        view=True,
    )
    [result] = announced
    Path(result.pop("log_path")).unlink()
    return result


def test_direct_route_pins_the_certificate_and_feeds_the_password_on_stdin(launched):
    result = _view(SETTINGS)
    argv = launched["argv"]
    assert launched["pins"] == [("windows-native-lab.tail.ts.net", 3389)]
    assert "/v:windows-native-lab.tail.ts.net:3389" in argv
    assert f"/cert:fingerprint:sha256:{FINGERPRINT}" in argv
    assert "/cert:ignore" not in argv
    assert "/d:winnative" in argv and "/u:yokeqa" in argv and "/d:" not in argv
    assert "/from-stdin:force" in argv and "/dynamic-resolution" in argv
    assert not any(arg.startswith(("/size:", "/smart-sizing:", "/bpp:")) for arg in argv)
    assert launched["stdin"] == PASSWORD + "\n"
    assert PASSWORD not in repr(argv) + repr(launched["kw"]) + json.dumps(result)
    assert launched["forward"] == ["open", "close"]
    assert result == {
        "user": "winnative\\yokeqa",
        "desktop_session": "native",
        "certificate_sha256": FINGERPRINT,
        "viewer": "closed",
        "client_exit_code": 0,
    }


def test_ssh_forward_ignores_the_loopback_certificate(launched):
    result = _view({**SETTINGS, "desktop_route": "ssh-forward", "user": "yokeqa"})
    argv = launched["argv"]
    assert launched["pins"] == []
    assert "/cert:ignore" in argv and "/v:127.0.0.1:49152" in argv
    assert "certificate_sha256" not in result and "display" not in result
    assert result["desktop_session"] == "native"


def test_bare_user_keeps_an_empty_domain(launched):
    _view({**SETTINGS, "desktop_user": "yokeqa"})
    assert "/u:yokeqa" in launched["argv"] and "/d:" in launched["argv"]


def test_begin_view_opens_the_native_viewer_until_close(launched):
    opened = desktop_access.begin_desktop_view(
        project="yoke", test_machine="windows-native-lab", settings=SETTINGS
    )
    assert launched["forward"] == ["open"]
    assert opened.session == {"desktop_session": "native", "certificate_sha256": FINGERPRINT}
    opened.close()
    Path(opened.log_path).unlink()
    assert launched["forward"] == ["open", "close"]
