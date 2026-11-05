# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)

from yoke_core.domain import deployment_run_ci_tested_source as tested

from yoke_core.domain import deployment_run_gate_branch_lineage as lineage

from yoke_core.domain.handlers import deployment_run_creation

HEAD, MIDDLE, OLDEST = "c" * 40, "b" * 40, "a" * 40

TARGET = tested.CiGateTarget(
    project="platform",
    flow="flow",
    repo="owner/platform",
    workflow="platform-ci.yml",
    branch="main",
    token="token",
    environment="prod",
)


def _run(
    sha: str,
    status: str,
    conclusion: str | None,
    number: int,
    *,
    event: str = "push",
    branch: str = "main",
) -> dict:
    return {
        "id": number,
        "run_number": number,
        "head_sha": sha,
        "head_branch": branch,
        "event": event,
        "status": status,
        "conclusion": conclusion,
    }


def _commit(sha: str, *parents: str) -> dict:
    return {"sha": sha, "parents": [{"sha": parent} for parent in parents]}


TRUNK = [_commit(HEAD, MIDDLE), _commit(MIDDLE, OLDEST), _commit(OLDEST)]


def _github(runs: list[dict], commits: list[dict] = TRUNK):
    """Answer the two reads creation makes: branch runs and branch commits."""

    def read(_target, path: str, query: dict) -> object:
        if path.endswith("/commits"):
            return commits
        wanted = query.get("head_sha")
        return {
            "workflow_runs": [
                run for run in runs if not wanted or run["head_sha"] == wanted
            ]
        }

    return read
