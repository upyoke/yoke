# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

import json

import os

import shutil

import subprocess

import sys

import tempfile

from pathlib import Path

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

sys.path.insert(0, _REPO_ROOT)

_SOURCE_PYTHONPATH_ENTRIES = (
    os.path.join(_REPO_ROOT, "packages", "yoke-contracts", "src"),
    os.path.join(_REPO_ROOT, "packages", "yoke-cli", "src"),
    os.path.join(_REPO_ROOT, "packages", "yoke-harness", "src"),
    os.path.join(_REPO_ROOT, "packages", "yoke-core", "src"),
    _REPO_ROOT,
)

from runtime.api.fixtures.file_test_db import init_test_db  # noqa: E402

_CLIENT = "yoke_core.api.service_client"


def _with_source_pythonpath(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a child env pinned to this checkout's package source roots."""
    child_env = os.environ.copy() if env is None else env.copy()
    entries = list(_SOURCE_PYTHONPATH_ENTRIES)
    existing = child_env.get("PYTHONPATH")
    if existing:
        entries.extend(existing.split(os.pathsep))

    deduped = []
    seen = set()
    for entry in entries:
        if entry and entry not in seen:
            deduped.append(entry)
            seen.add(entry)
    child_env["PYTHONPATH"] = os.pathsep.join(deduped)
    return child_env


def _service_client_cmd(args: list[str]) -> list[str]:
    return [sys.executable, "-m", _CLIENT] + list(args)


def _run_client(args: list[str], db_path: str = None) -> subprocess.CompletedProcess:
    """Run the service client with optional YOKE_DB override.

    When ``args`` contains ``--session-id <sid>``, also export
    ``YOKE_SESSION_ID=<sid>`` so the subprocess's ambient session
    matches the explicit value. The ``service_client_work_claims``
    self-only identity check rejects mismatched explicit/ambient
    pairs, and tests faithfully model the real harness contract where
    the harness sets ``YOKE_SESSION_ID`` before invoking the CLI.
    """
    env = os.environ.copy()
    if db_path:
        env["YOKE_DB"] = db_path
    if "--session-id" in args:
        sid_index = args.index("--session-id") + 1
        if sid_index < len(args):
            env["YOKE_SESSION_ID"] = args[sid_index]
    return subprocess.run(
        _service_client_cmd(args),
        capture_output=True,
        text=True,
        env=_with_source_pythonpath(env),
        cwd=_REPO_ROOT,
        timeout=30,
    )
