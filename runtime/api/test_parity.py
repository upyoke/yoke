"""Shared service-client subprocess helper for parity tests.

The parity tests proper live in split sibling modules
(``test_parity_render``, ``test_parity_render_board``,
``test_parity_db_router_*``, ``test_parity_service_client_*``). Their strict
project-identity schemas and seed data live in
``parity_service_client_project_fixture`` and
``parity_db_router_test_fixtures``. This module intentionally only exports
the subprocess helpers they share.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLIENT = "yoke_core.api.service_client"
_DB_ROUTER = "yoke_core.cli.db_router"
_DB_ROUTER_ITEM_ALIASES = {
    "item-list": ("items", "list"),
    "item-count": ("items", "count"),
    "item-get": ("items", "get"),
    "item-row": ("items", "row"),
    "item-progress": ("items", "progress"),
}


def _run_service_client(db_path: str, *args: str) -> subprocess.CompletedProcess:
    """Run service_client.py with the given arguments and YOKE_DB."""
    env = os.environ.copy()
    env["YOKE_DB"] = db_path
    if args and args[0] == "create-item":
        env["YOKE_IDEA_INTAKE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", _CLIENT] + list(args),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def _run_db_router(db_path: str, *args: str) -> subprocess.CompletedProcess:
    """Run db_router through its package module against the given YOKE_DB."""
    env = os.environ.copy()
    env["YOKE_DB"] = db_path
    router_args = list(args)
    if router_args and router_args[0] in _DB_ROUTER_ITEM_ALIASES:
        router_args = [
            *_DB_ROUTER_ITEM_ALIASES[router_args[0]],
            *router_args[1:],
        ]
    return subprocess.run(
        [sys.executable, "-m", _DB_ROUTER, *router_args],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=_REPO_ROOT,
    )
