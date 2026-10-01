"""A recorded screenshot remains immediately readable on the executing client."""

from __future__ import annotations

import base64
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from yoke_cli.commands.adapters import test_machine as cli
from yoke_cli.commands.adapters import test_machine_operation as operations
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_harness.test_machine_operations import LocalHostControlSubmission


def png_payload():
    image = Image.new("RGB", (40, 30), "white")
    image.putpixel((0, 0), (0, 0, 0))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return {
        "artifacts": [{"content_base64": base64.b64encode(stream.getvalue()).decode()}]
    }


@pytest.mark.parametrize("status", ["verified", "error"])
def test_screenshot_cli_keeps_only_accepted_png_and_fails_error_receipt(
    tmp_path, monkeypatch, capsys, status
):
    payload = png_payload()
    payload.update(
        {"operation": "screenshot", "status": status, "checks": [], "error_code": None}
    )
    responses = iter(
        [
            FunctionCallResponse(
                success=True,
                function="test_machine.operation.begin",
                version="v1",
                result={"execution": {"lease_id": 23, "contract_digest": "digest"}},
            ),
            FunctionCallResponse(
                success=True,
                function="test_machine.operation.submit",
                version="v1",
                result={"status": status, "checks": []},
            ),
        ]
    )
    monkeypatch.setattr(operations, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(operations, "call_dispatcher", lambda **kwargs: next(responses))
    monkeypatch.setattr(
        "yoke_harness.test_machine_operations.execute_host_operation_contract",
        lambda *args, **kwargs: LocalHostControlSubmission(payload),
    )
    destination = tmp_path / "desktop.png"
    monkeypatch.setattr(
        "yoke_contracts.free_paths.private_free_path",
        lambda *args, **kwargs: destination,
    )
    code = cli.test_machine_screenshot(
        ["--project", "yoke", "--machine", "test", "--json"]
    )
    response = json.loads(capsys.readouterr().out)
    assert code == (0 if status == "verified" else 1)
    assert destination.exists() is (status == "verified")
    if status == "verified":
        assert Path(response["result"]["artifact_path"]) == destination
        assert destination.read_bytes() == base64.b64decode(
            payload["artifacts"][0]["content_base64"]
        )
        assert destination.stat().st_mode & 0o777 == 0o600
    else:
        assert "artifact_path" not in response["result"]


def test_invalid_capture_never_leaves_local_png(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "yoke_contracts.free_paths.private_free_path",
        lambda *args, **kwargs: tmp_path / "desktop.png",
    )
    with pytest.raises(ValueError, match="screenshot_png_invalid"):
        operations.retain_screenshot({"artifacts": [{"content_base64": "bad"}]})
    assert not (tmp_path / "desktop.png").exists()
