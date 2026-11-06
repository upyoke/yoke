# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run

import io

import json

import urllib.error

from typing import Any

import pytest

from runtime.api.domain.deployment_qa_frozen_target_authority_test_support import (
    _edit_stage_settings,
    _materialized_stage,
)

from runtime.api.domain.deployment_qa_stage_execution_test_support import _environment

from yoke_core.domain import deployment_qa_release_version

from yoke_core.domain.project_file_at_commit import (
    ProjectFileAbsent,
    ProjectFileUnreadable,
)

from yoke_core.domain.qa_requirement_target_rebind import rebind_requirement

BASE_URL = "https://distribution.example.test"

PIN_FILE = "yoke-release-pin.txt"

PINNED = "0.1.1+launch.590"

NEWER = "0.1.1+launch.591"


def _pin_capability(conn: Any, project_id: int = 1, **extra: Any) -> None:
    settings = {"desired_pin_path": "release.yoke_pin", **extra}
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(%s,'release_pin',%s,%s) ON CONFLICT(project_id,type) "
        "DO UPDATE SET settings=EXCLUDED.settings",
        (project_id, json.dumps(settings), "2026-10-07T00:00:00Z"),
    )
    conn.commit()


def _stage(conn: Any, *, channel: str | None = "latest", leaf: str = NEWER) -> None:
    """Stage settings whose desired-pin leaf a later release already moved."""
    distribution = {"base_url": BASE_URL}
    if channel is not None:
        distribution["channel"] = channel
    _environment(conn)
    _edit_stage_settings(
        conn, {"distribution": distribution, "release": {"yoke_pin": leaf}}
    )
