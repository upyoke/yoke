"""The create handler's idempotency key: validation, replay, and conflict."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_core.domain.deployment_run_create_idempotency import (
    IdempotencyKeyConflict,
)
from yoke_core.domain.deployment_run_create_write import CreatedRun
from yoke_core.domain.handlers import deployment_run_creation, deployment_runs

REPLAY = "yoke_core.domain.deployment_run_create_idempotency.replay_run"
CREATE = "yoke_core.domain.deployment_runs_crud_mutate.create_run"
ROW = (
    "run-20260928-006|yoke|yoke-hosted-prod|persistent|prod|"
    "||created||2026-09-28T00:00:00Z|||operator"
)


def _create(key):
    payload = {"project": "yoke", "flow": "yoke-hosted-prod", "idempotency_key": key}
    return deployment_runs.handle_deployment_run_create(
        _request(function="deployment_runs.create", payload=payload)
    )


def test_blank_key_is_refused() -> None:
    outcome = _create("  ")

    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.idempotency_key"


def test_replay_returns_the_recorded_run_without_creating() -> None:
    with (
        patch(REPLAY, return_value="run-20260928-006"),
        patch(CREATE) as create,
        patch("yoke_core.domain.deployment_runs_crud_query.cmd_get", return_value=ROW),
        patch.object(deployment_run_creation, "_member_item_ids", return_value=()),
    ):
        outcome = _create("k1")

    assert outcome.primary_success
    assert outcome.result_payload["run_id"] == "run-20260928-006"
    assert outcome.result_payload["replayed"] is True
    assert outcome.result_payload["idempotency_key"] == "k1"
    assert outcome.result_payload["idempotency_basis"] == "recorded_key"
    create.assert_not_called()


def test_fresh_keyed_create_passes_key_and_canonical_request() -> None:
    with (
        patch(REPLAY, return_value=None),
        patch(
            CREATE, return_value=CreatedRun("run-20260928-006", False, "recorded_key")
        ) as create,
        patch("yoke_core.domain.deployment_runs_crud_query.cmd_get", return_value=ROW),
        patch.object(deployment_run_creation, "_member_item_ids", return_value=()),
    ):
        outcome = _create(" k1 ")

    assert outcome.result_payload["replayed"] is False
    assert outcome.result_payload["idempotency_basis"] == "recorded_key"
    assert create.call_args.kwargs["idempotency_key"] == "k1"
    assert '"flow":"yoke-hosted-prod"' in create.call_args.kwargs["create_request"]


def test_conflict_refuses_by_name() -> None:
    conflict = IdempotencyKeyConflict("k1", "run-20260928-006", ["release_lineage"])
    with patch(REPLAY, side_effect=conflict):
        outcome = _create("k1")

    assert outcome.error.code == "idempotency_key_conflict"
    assert "run-20260928-006" in outcome.error.message
    assert "release_lineage" in outcome.error.message


def test_conflict_found_inside_the_locked_create_refuses_by_name() -> None:
    conflict = IdempotencyKeyConflict("k1", "run-20260928-006", ["environment"])
    with (
        patch(REPLAY, return_value=None),
        patch(CREATE, side_effect=conflict),
    ):
        outcome = _create("k1")

    assert outcome.error.code == "idempotency_key_conflict"
