# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import datetime

import threading

from pathlib import Path

from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)

from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    CARRIER_ITEM_ID,
    CONSUMER_ITEM_ID,
    two_project_release,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.carried_release_candidate import insert_run

from yoke_core.domain import deploy_pipeline_github_workflow_bindings as branch_reads

from yoke_core.domain import deployment_run_create_idempotency as idempotency

from yoke_core.domain import deployment_run_create_write as create_write

from yoke_core.domain import deployment_run_carried_work_sources as carried_sources

from yoke_core.domain.deployment_prepared_source import PreparedSource

from yoke_core.domain.deployment_source_reads import prepared_sources_only

from yoke_core.domain.schema_read_scope import composition_reads

from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource

from yoke_core.domain.deployment_run_create_write import CreatedRun, create_run

from yoke_core.domain.handlers import deployment_run_execution as execution

from yoke_contracts.api.function_call import TargetRef

from yoke_contracts.timestamps import parse_instant


def _release(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE deployment_flows SET status='active' WHERE id=%s", (CARRIER_FLOW,)
    )
    test_db.execute("DELETE FROM deployment_runs WHERE id='run-candidate'")
    test_db.commit()
    return release


def _carrier_tip(release: dict[str, Any]) -> str:
    from runtime.api.fixtures.carried_release_candidate import git

    return git(release["carrier_repo"], "rev-parse", "HEAD").strip()
