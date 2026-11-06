# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from unittest import mock

import pytest

from yoke_core.domain import standalone_item_merge as merge_domain

from yoke_core.domain import standalone_item_merge_landed as landed

from yoke_core.domain import standalone_item_merge_cli as merge_cli

from yoke_core.domain import standalone_item_merge_verify as verify

from yoke_core.domain import standalone_item_merge_recovery as merge_recovery

from yoke_core.domain import standalone_item_merge_qa as merge_qa

from runtime.api.domain.merge_route_gate_stubs import admit_route_gates

MERGING_SHA = "b" * 40


def _item(requirement: dict | None) -> dict:
    requirements = [] if requirement is None else [requirement]
    return {
        "id": 10,
        "public_ref": "YOK-10",
        "status": "reviewing-implementation",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
        "worktrees": [
            {
                "branch": "YOK-10",
                "path": "/tmp/YOK-10",
                "commit_sha": MERGING_SHA,
            }
        ],
        "qa_plan_attachments": [{"case_count": 1, "materialized_count": 1}],
        "qa_requirements": requirements,
    }


def _requirement(
    *,
    verdict: str,
    sha: str,
    completed: bool = True,
    requirement_id: int = 77,
    transition_id: str | None = None,
) -> dict:
    return {
        "id": requirement_id,
        "blocking_mode": "blocking",
        "current_passing_proof": True,
        "subject_proof_error": "",
        "human_review": None,
        "waived_at": None,
        "run_id": 88,
        "verdict": verdict,
        "case_outcome": "failed" if verdict != "pass" else "passed",
        "execution_status": "captured",
        "completed_at": "2026-01-01T00:00:00Z" if completed else None,
        "recorded_head_sha": sha,
        "workflow_transition_id": transition_id,
    }
