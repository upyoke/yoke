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
    return SimpleNamespace(os="linux", _run=run), captures, commands


@pytest.mark.parametrize("session", ["started", "reused"])
def test_only_new_desktop_waits_for_first_nonblank_frame(monkeypatch, session):
    control, captures, commands = host(
        monkeypatch, session=session, frames=[png(blank=True), png()]
    )
    result = capture.capture_desktop(control)
    assert result.ok == (session == "started")
    assert len(captures) == (2 if session == "started" else 1)
    assert commands[-1].startswith("rm -f /tmp/yoke-desktop-")
    if result.ok:
        assert result.evidence["desktop_session"] == "started"
        assert result.evidence["width"] == 80 and result.evidence["height"] == 60
        assert captures[0] == captures[1]
    else:
        assert "blank desktop" in result.evidence["recovery"]


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
