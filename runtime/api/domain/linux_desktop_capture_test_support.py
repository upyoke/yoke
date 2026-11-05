# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
