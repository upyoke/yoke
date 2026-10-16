"""Retry create rejects an unpinned source run without a traceback."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_core.domain.handlers import deployment_runs


def test_run_create_rejects_unpinned_retry_without_traceback():
    source = {
        "id": "run-old",
        "project": "yoke",
        "flow": "yoke-hosted-prod",
        "target_tier": "persistent",
        "target_environment": "prod",
        "release_lineage": None,
        "status": "failed",
        "current_stage": "release",
        "created_at": "2026-06-15T00:00:00Z",
        "started_at": None,
        "completed_at": "2026-06-15T01:00:00Z",
        "created_by": "operator",
    }
    with patch(
        "yoke_core.domain.deployment_runs_crud_query.get_run",
        return_value=source,
    ):
        outcome = deployment_runs.handle_deployment_run_create(
            _request(
                function="deployment_runs.create",
                payload={
                    "project": "yoke",
                    "flow": "yoke-hosted-prod",
                    "retry_of": "run-old",
                },
            )
        )
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "run_create_rejected"
    assert "no pinned release lineage" in outcome.error.message
