# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)

from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn

from yoke_contracts.machine_screenshot import screenshot_png

from yoke_core.domain.handlers.machine_qa_operation import handle_operation_submit

from yoke_harness.ssh_machine_screenshot import capture_desktop

from yoke_contracts.test_machine_types import HostActionResult


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
