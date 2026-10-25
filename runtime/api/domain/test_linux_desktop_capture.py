"""Linux first-frame readiness keeps startup evidence and rejects bad captures."""

import base64
from io import BytesIO
import subprocess
from types import SimpleNamespace

from PIL import Image
import pytest

from yoke_harness import ssh_machine_screenshot as capture


def png(*, blank=False):
    image = Image.new("RGB", (80, 60), "black")
    if not blank:
        image.putpixel((0, 0), (255, 255, 255))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode()


def host(monkeypatch, *, session, frames):
    captures = []
    commands = []
    restarts = []

    def desktop(control, argv, **kwargs):
        captures.append(argv)
        result = subprocess.CompletedProcess(argv, 0, "", "")
        result.desktop_session = session if len(captures) == 1 else "reused"
        return result

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, frames.pop(0) if command.startswith("base64") else "", ""
        )

    monkeypatch.setattr("yoke_harness.linux_desktop_session.desktop_command", desktop)
    monkeypatch.setattr(capture.time, "sleep", lambda _: None)
    monkeypatch.setattr("yoke_harness.linux_desktop_session.ensure_desktop",
                        lambda control, **kw: restarts.append(kw))
    return SimpleNamespace(os="linux", _run=run, restarts=restarts), captures, commands


@pytest.mark.parametrize("os", ["linux", "windows"])
@pytest.mark.parametrize("session", ["started", "reused", "restarted"])
def test_blank_desktop_recovers_first_frame(monkeypatch, session, os):
    control, captures, commands = host(
        monkeypatch, session=session, frames=[png(blank=True), png()]
    )
    control.os = os
    result = capture.capture_desktop(control)
    assert result.ok
    assert len(captures) == 2
    assert control.restarts == ([{"restart": True}] if session == "reused" else [])
    assert result.evidence["desktop_session"] == (
        "restarted" if session == "reused" else session
    )
    assert result.evidence["width"] == 80 and result.evidence["height"] == 60
    assert captures[0] == captures[1]
    assert commands[-1].startswith("rm -f /tmp/yoke-desktop-")


def test_new_desktop_blank_frame_has_bounded_refusal(monkeypatch):
    control, captures, commands = host(
        monkeypatch, session="started", frames=[png(blank=True)]
    )
    ticks = iter((0, 16))
    monkeypatch.setattr(capture.time, "monotonic", lambda: next(ticks))
    result = capture.capture_desktop(control)
    assert not result.ok and result.error_code == "screenshot_png_invalid"
    assert "blank desktop" in result.evidence["recovery"]
    assert len(captures) == 1 and commands[-1].startswith("rm -f ")


def test_new_desktop_malformed_png_is_not_a_render_wait(monkeypatch):
    control, captures, _ = host(monkeypatch, session="started", frames=["not base64"])
    result = capture.capture_desktop(control)
    assert not result.ok and result.error_code == "screenshot_png_invalid"
    assert len(captures) == 1


def test_reused_desktop_restarts_once_then_reports_logs(monkeypatch):
    control, captures, commands = host(
        monkeypatch, session="reused", frames=[png(blank=True), png(blank=True)]
    )
    ticks = iter((0, 0, 16))
    monkeypatch.setattr(capture.time, "monotonic", lambda: next(ticks))
    result = capture.capture_desktop(control)
    assert not result.ok and result.error_code == "screenshot_png_invalid"
    assert control.restarts == [{"restart": True}]
    assert len(captures) == 2
    assert "desktop_session=restarted" in result.evidence["recovery"]
    assert "~/.xsession-errors" in result.evidence["recovery"]
    assert any("/var/log/xrdp-sesman.log" in command for command in commands)


def test_reused_malformed_png_does_not_restart(monkeypatch):
    control, captures, _ = host(monkeypatch, session="reused", frames=["bad"])
    result = capture.capture_desktop(control)
    assert not result.ok and result.error_code == "screenshot_png_invalid"
    assert len(captures) == 1 and control.restarts == []
