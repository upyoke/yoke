# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import time

import urllib.error

from datetime import datetime, timezone

from typing import Any

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)

from yoke_core.domain import deployment_qa_release_version

from yoke_core.domain import deployment_qa_stage_outstanding as outstanding

from yoke_core.domain.deployment_run_auto_completion import _readiness

from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item

from yoke_core.domain.post_deploy_verification_answer import (
    NOT_REQUIRED,
    PostDeployAnswer,
)

from yoke_core.domain.steering_fleet_report_run_progress import run_progress

RUN = "run-pinned-release-reads"

LINEAGE = "d" * 40

MEMBERS = tuple(range(9701, 9751))

PIN_FILE = "yoke-release-pin.txt"

PINNED = "0.1.1+launch.700"

BASE_URL = "https://distribution.example.test"

def _seed(conn: Any) -> None:
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(1,'release_pin',%s,'2026-10-14T00:00:00Z') "
        "ON CONFLICT(project_id,type) DO UPDATE SET settings=EXCLUDED.settings",
        (
            json.dumps(
                {
                    "desired_pin_path": "release.yoke_pin",
                    "candidate_pin_file": PIN_FILE,
                }
            ),
        ),
    )
    plan_id = create_smoke_plan(conn, project="yoke", slug=f"smoke-{RUN}")
    seed_run_standing_on_qa_stage(
        conn,
        run_id=RUN,
        project="yoke",
        stages=item_qa_stage_definitions(plan_id),
        members=MEMBERS,
        lineage=LINEAGE,
    )
    conn.execute(
        "UPDATE environments SET settings=%s WHERE project_id=1 AND name='stage'",
        (json.dumps({"distribution": {"base_url": BASE_URL}}),),
    )
    conn.execute(
        "UPDATE items SET status='release' WHERE id = ANY(%s)", (list(MEMBERS),)
    )
    conn.commit()

def _count_release_reads(monkeypatch) -> dict[str, int]:
    counts = {"pin_file": 0, "published": 0}
    published = deployment_qa_release_version.release_records_url(BASE_URL, PINNED)

    def read(conn: Any, project_id: int, sha: str, path: str) -> bytes:
        counts["pin_file"] += 1
        assert (sha, path) == (LINEAGE, PIN_FILE)
        return f"{PINNED}\n".encode()

    def fetch(url: str) -> bytes:
        counts["published"] += 1
        if url != published:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO())
        return b'[{"filename": "yoke-0.1.1-py3-none-any.whl"}]'

    monkeypatch.setattr(deployment_qa_release_version, "read_project_file", read)
    monkeypatch.setattr(deployment_qa_release_version, "_fetch", fetch)
    return counts
