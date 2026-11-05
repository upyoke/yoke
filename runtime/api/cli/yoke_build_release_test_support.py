# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import base64

import contextlib

import hashlib

import json

import zipfile

from pathlib import Path

import pytest

from yoke_core.tools import build_release, package_index, release_artifacts


def _write_wheel(wheelhouse: Path, *, name: str, version: str) -> None:
    dist = name.replace("-", "_")
    filename = f"{dist}-{version}-py3-none-any.whl"
    metadata_text = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    for sibling in package_index.PRODUCT_SIBLING_DEPENDENCIES.get(name, ()):
        metadata_text += f"Requires-Dist: {sibling}\n"
    metadata = metadata_text.encode("utf-8")
    wheel_metadata = (
        b"Wheel-Version: 1.0\nGenerator: test\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    dist_info = f"{dist}-{version}.dist-info"
    files = {
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": wheel_metadata,
    }
    if name == "yoke-core":
        files["yoke_core/domain/migrations/0001_test_entry.py"] = (
            b"def apply(conn):\n    pass\n"
        )
    record_arcname = f"{dist_info}/RECORD"
    record_lines = [
        f"{arcname},{_record_hash(data)},{len(data)}" for arcname, data in files.items()
    ]
    record_lines.append(f"{record_arcname},,")
    files[record_arcname] = ("\n".join(record_lines) + "\n").encode("utf-8")
    with zipfile.ZipFile(wheelhouse / filename, "w") as archive:
        for arcname, data in files.items():
            archive.writestr(arcname, data)


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"
