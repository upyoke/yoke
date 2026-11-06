# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.lint_lane_main_write_shell_redirect_test_support import repo as repo
from runtime.api.domain.lint_lane_main_write_shell_redirect_test_support import conn as conn

import os

from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)

from runtime.api.fixtures.machine_config_test import register_machine_checkout

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain import lint_lane_main_write, lint_session_cwd

from yoke_core.domain.lint_lane_main_write_classify import is_write_operation

from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)

from yoke_core.domain.lint_session_cwd_path_authority import free_path_prefixes

from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
    extract_payload_write_targets,
)

HOLDER = "sid-holder"

HELD_ITEM = 2220


def _register(repo):
    register_machine_checkout(Path(repo).parent / "machine-config", Path(repo), 1)


def _seed_lane(conn, repo, *, session_id=HOLDER, item_id=HELD_ITEM):
    _register(repo)
    seed_item(conn, item_id=item_id, branch=f"YOK-{item_id}", repo_path=repo)
    seed_item_claim(conn, session_id, item_id=item_id)
    lane = repo / ".worktrees" / f"YOK-{item_id}"
    lane.mkdir(parents=True, exist_ok=True)
    return lane
