# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import subprocess

from pathlib import Path

from unittest.mock import patch

import pytest

from yoke_core.domain.qa_case_execution import QaCaseExecutionError

from yoke_core.domain.qa_case_tree_binding_scope import (
    candidate_revision,
    evaluate_deployment_binding,
    session_lane_binds_case,
)

from yoke_core.domain.qa_case_worktree_run import execute_worktree_case

RUN_ID = "run-20260101-001"

CANDIDATE = "a" * 40


def _deployment_case(**overrides) -> dict:
    case = {
        "requirement_id": 27758,
        "public_ref": None,
        "project_id": 1,
        "project": "yoke",
        "case_key": "release-health",
        "deployment_run_id": RUN_ID,
        "deployment_stage": "item-qa",
        "method_config": {"command": "true"},
        "execution_target": {
            "deployment": {
                "run_id": RUN_ID,
                "stage": "item-qa",
                "release_lineage": CANDIDATE,
            },
            "endpoints": {"app_url": "https://app.example.test"},
            "observed_url": "https://app.example.test",
        },
    }
    case.update(overrides)
    return case
