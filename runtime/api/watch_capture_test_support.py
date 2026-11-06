# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

import shutil

import tempfile

import time

import unittest

import uuid

from yoke_contracts.watch_capture import (
    EXIT_SENTINEL,
    capture_file_completed,
    capture_state,
)


def sentinel_line(kind: str, rc: int, raw_path: str) -> str:
    """Build the footer ``yoke_core.tools._watch_runner.run_watcher`` writes."""
    return f"# watch_{kind} exit={rc} raw={raw_path}\n"


class CapturePairHelpers:
    """Build real watcher raw+progress capture pairs in a temp dir.

    Plain mixin (not a ``TestCase``) so it is not collected on its own.
    """

    def _make_pair(self, kind: str = "merge") -> tuple[str, str]:
        # The nonce keeps parallel (pytest-xdist) workers from colliding.
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        nonce = uuid.uuid4().hex
        raw = os.path.join(tmpdir, f"yoke-{kind}.raw.{nonce}.log")
        progress = os.path.join(tmpdir, f"yoke-{kind}.progress.{nonce}.log")
        return raw, progress

    @staticmethod
    def _write(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    @staticmethod
    def _touch_old(path: str, age_seconds: float = 600) -> None:
        old = time.time() - age_seconds
        os.utime(path, (old, old))
