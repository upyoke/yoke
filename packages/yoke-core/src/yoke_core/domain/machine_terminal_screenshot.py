"""Retain a desktop checkpoint for the existing Machine QA artifact transfer."""

from __future__ import annotations

import tempfile
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_contracts.machine_screenshot import screenshot_png
from yoke_core.domain.qa_artifact_handle import local_handle


def capture_terminal_checkpoint(control) -> dict:
    """Write validated screenshot bytes into owner-only local evidence scratch."""
    result = control.capture_screenshot()
    if not result.ok:
        raise RuntimeError(
            result.error_code + ": " + str(result.evidence.get("recovery"))
        )
    content, _size = screenshot_png(
        result.evidence["capture_artifact"]["content_base64"]
    )
    parent = machine_config.yoke_home() / "qa-host-control"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=parent, suffix=".png", delete=False) as stream:
        stream.write(content)
        path = Path(stream.name)
    return {"artifact_handle": local_handle(str(path), "image/png")}
