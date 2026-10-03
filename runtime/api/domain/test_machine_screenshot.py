"""Desktop transport, PNG validation, and operation-receipt artifact authority."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import subprocess
from types import SimpleNamespace

from PIL import Image
import pytest

from runtime.api.domain.machine_operation_test_support import (
    operation_receipts,
    operation_request,
    run_operation,
)
from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn
from yoke_contracts.machine_screenshot import screenshot_png
from yoke_core.domain.handlers.machine_qa_operation import handle_operation_submit
from yoke_harness.ssh_machine_screenshot import capture_desktop
from yoke_harness.test_machine_types import HostActionResult


def png():
    image = Image.new("RGB", (80, 60), "white")
    image.putpixel((0, 0), (0, 0, 0))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def screenshot_result():
    content = png()
    return HostActionResult(
        True,
        {
            "os": "macos",
            "width": 80,
            "height": 60,
            "sha256": hashlib.sha256(content).hexdigest(),
            "artifact_token": "desktop",
            "capture_artifact": {
                "token": "desktop",
                "filename": "desktop.png",
                "content_type": "image/png",
                "content_base64": base64.b64encode(content).decode(),
            },
        },
    )


@pytest.mark.parametrize("value", ["invalid", base64.b64encode(b"not PNG").decode()])
def test_unusable_png_refuses(value):
    with pytest.raises(ValueError, match="screenshot_png_invalid"):
        screenshot_png(value)


def test_blank_desktop_is_not_evidence():
    stream = BytesIO()
    Image.new("RGB", (80, 60), "black").save(stream, format="PNG")
    with pytest.raises(ValueError, match="screenshot_png_invalid"):
        screenshot_png(base64.b64encode(stream.getvalue()).decode())


def test_capture_failure_is_named_and_cleanup_still_runs(monkeypatch):
    commands = []
    monkeypatch.setattr(
        "yoke_harness.ssh_mac_host_session_state.probe_host_display_context",
        lambda run, **kwargs: {"console_user": "test", "display_locked": False},
    )

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, "", "capture denied")

    monkeypatch.setattr(
        "yoke_harness.ssh_mac_gui_session.run_terminal_app_command",
        lambda run, **kwargs: run("screencapture"),
    )
    result = capture_desktop(SimpleNamespace(os="macos", _run=run, _user="test"))
    assert not result.ok and result.error_code == "desktop_screenshot_failed"
    assert "recovery" in result.evidence
    assert commands[-1].startswith("rm -f")


def test_screenshot_operation_stores_handle_and_replay_does_not_upload(
    tmp_path, monkeypatch
):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    uploads = []
    handle = {
        "backend": "local",
        "path": str(tmp_path / "desktop.png"),
        "content_type": "image/png",
    }

    def store(conn, **kwargs):
        uploads.append(kwargs)
        return handle

    monkeypatch.setattr(
        "yoke_core.domain.handlers.machine_qa_screenshot_artifact.store_owned_artifact_bytes",
        store,
    )
    control = FakeHostControl()
    control.capture_screenshot = screenshot_result
    submitted, execution = run_operation("screenshot", control=control)
    assert submitted.primary_success, submitted.error
    assert uploads[0]["content"] == png()
    assert uploads[0]["owner"]["artifact_subject"].startswith("test-machine-")
    [receipt] = operation_receipts(conn)
    assert receipt["checks"][0]["artifact_handle"] == handle
    assert "artifact_token" not in receipt["checks"][0]
    result = screenshot_result().evidence
    artifact = result.pop("capture_artifact")
    replay = handle_operation_submit(
        operation_request(
            {
                "project": "yoke",
                "lease_id": execution["lease_id"],
                "contract_digest": execution["contract_digest"],
                "operation": "screenshot",
                "status": "verified",
                "error_code": None,
                "checks": [{"name": "screenshot", "ok": True, **result}],
                "artifacts": [artifact],
            }
        )
    )
    assert replay.primary_success, replay.error
    assert len(uploads) == 1


def test_failing_screenshot_records_error_without_artifact(tmp_path, monkeypatch):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    control = FakeHostControl()
    control.capture_screenshot = lambda: HostActionResult(
        False, {"recovery": "Unlock desktop"}, "desktop_locked"
    )
    submitted, _execution = run_operation("screenshot", control=control)
    assert submitted.primary_success, submitted.error
    [receipt] = operation_receipts(conn)
    assert receipt["status"] == "error" and receipt["error_code"] == "desktop_locked"


@pytest.mark.parametrize(
    "context,code",
    [
        (
            {"console_user": "other", "display_locked": False},
            "terminal_console_user_mismatch",
        ),
        ({"console_user": "test", "display_locked": True}, "terminal_display_locked"),
        ({"console_user": "test", "display_locked": None}, "terminal_display_locked"),
        (
            {
                "console_user": "test",
                "display_locked": True,
                "screen_sharing_active": True,
            },
            "terminal_display_locked",
        ),
    ],
)
def test_mac_private_or_locked_session_is_not_captured(monkeypatch, context, code):
    commands = []
    monkeypatch.setattr(
        "yoke_harness.ssh_mac_host_session_state.probe_host_display_context",
        lambda run, **kwargs: context,
    )

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    result = capture_desktop(SimpleNamespace(os="macos", _run=run, _user="test"))
    assert not result.ok and result.error_code == code
    assert all(command.startswith("rm -f") for command in commands)
    assert "capture_artifact" not in result.evidence
    if context.get("screen_sharing_active"):
        assert (
            "display is curtained by an active Screen Sharing connection"
            in result.evidence["recovery"]
        )
        assert (
            "disconnect Screen Sharing (or reconnect without curtain) and retry"
            in result.evidence["recovery"]
        )
    elif code == "terminal_display_locked":
        from yoke_contracts.machine_qa_terminal_bridge import terminal_bridge_recovery

        assert result.evidence["recovery"] == terminal_bridge_recovery(code)


@pytest.mark.parametrize("tamper", ["digest", "dimensions", "bytes", "handle", "os"])
def test_untrusted_screenshot_receipt_never_creates_artifact(
    tmp_path, monkeypatch, tamper
):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    uploads = []
    monkeypatch.setattr(
        "yoke_core.domain.handlers.machine_qa_screenshot_artifact.store_owned_artifact_bytes",
        lambda *args, **kwargs: uploads.append(kwargs),
    )
    result = screenshot_result()
    if tamper == "digest":
        result.evidence["sha256"] = "wrong"
    if tamper == "os":
        result.evidence["os"] = "windows"
    if tamper == "dimensions":
        result.evidence["width"] = 81
    if tamper == "bytes":
        result.evidence["capture_artifact"]["content_base64"] = base64.b64encode(
            b"not PNG"
        ).decode()
    if tamper == "handle":
        result.evidence["artifact_handle"] = {
            "backend": "local",
            "path": "/private/forged.png",
        }
    control = FakeHostControl()
    control.capture_screenshot = lambda: result
    submitted, _execution = run_operation("screenshot", control=control)
    assert not submitted.primary_success
    assert not uploads and not operation_receipts(conn)


def test_artifact_store_failure_is_named_without_success_receipt(tmp_path, monkeypatch):
    from yoke_core.domain.qa_artifact_storage import ArtifactStorageError

    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)

    def refuse(*args, **kwargs):
        raise ArtifactStorageError("s3_upload_failed", "upload refused")

    monkeypatch.setattr(
        "yoke_core.domain.handlers.machine_qa_screenshot_artifact.store_owned_artifact_bytes",
        refuse,
    )
    control = FakeHostControl()
    control.capture_screenshot = screenshot_result
    submitted, _execution = run_operation("screenshot", control=control)
    assert not submitted.primary_success and submitted.error.code == "s3_upload_failed"
    assert not operation_receipts(conn)
