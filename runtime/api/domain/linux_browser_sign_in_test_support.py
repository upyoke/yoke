# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import hashlib

import io

import json

import os

import subprocess

import sys

import tarfile

import pytest

from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM

from yoke_harness.ssh_linux_preserved_entries import SNAP_CHROMIUM_HOME_ENTRY


def operation(home, golden, action):
    result = subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, action, str(home), str(golden)],
        input="[]",
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
    )
    return result, json.loads(result.stdout.splitlines()[-1])
