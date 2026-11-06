# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import tarfile

from pathlib import Path

import pytest

from yoke_core.domain import universe_archive as ua

from yoke_core.domain.json_helper import dumps_pretty

from yoke_core.domain.source_freeze_intent import file_sha256


def _receipt_for(dump: Path) -> dict:
    return {
        "freeze_intent": {
            "schema": "yoke.source-freeze/v2",
            "database": {"name": "yoke", "oid": 7, "org": "default"},
            "archive": {
                "sha256": file_sha256(dump),
                "bytes": dump.stat().st_size,
                "catalog_digest": "d" * 64,
            },
        },
        "source_authority": {"receipt_digest": "stable"},
    }
