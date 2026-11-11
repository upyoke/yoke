"""A release set binds one source, from the flow that waits for CI first."""

from __future__ import annotations

from dataclasses import replace
from unittest import mock

import pytest

from runtime.api.domain.deployment_run_ci_tested_source_test_support import (
    HEAD,
    MIDDLE,
    TARGET,
    _github,
    _run,
)
from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain import deployment_run_create_set_source as set_source
from yoke_core.domain import deployment_run_gate_branch_lineage as lineage
from yoke_core.domain.deployment_run_create_write import CreatedRun
from yoke_core.domain.handlers import deployment_run_creation

STAGE, PRODUCTION = "hosted-stage", "hosted-production"


@pytest.fixture
def stage_and_production():
    """Stage binds the tip without waiting for CI; Production waits for it."""
    runs = [
        _run(HEAD, "completed", "success", 3, event="merge_group"),
        _run(MIDDLE, "completed", "success", 1),
    ]

    def target(_project, flow, _environment, *, ci_only=False):
        if flow == PRODUCTION:
            return replace(TARGET, flow=flow)
        return None if ci_only else replace(TARGET, flow=flow, workflow="")

    def dispatch(_target):
        runs.append(_run(HEAD, "in_progress", None, 4, event="workflow_dispatch"))
        return HEAD

    with (
        mock.patch.object(tested, "ci_gate_target", side_effect=target),
        mock.patch.object(set_source, "ci_gate_target", side_effect=target),
        mock.patch.object(lineage, "previous_release", return_value=None),
        mock.patch.object(tested, "_read", side_effect=lambda *a: _github(runs)(*a)),
        mock.patch.object(tested, "dispatch_branch_ci", side_effect=dispatch) as sent,
    ):
        yield sent


def test_tip_with_only_merge_group_ci_dispatches_once_for_the_set(stage_and_production):
    bound = set_source.bind_set_source("platform", [STAGE, PRODUCTION], None)

    assert bound == HEAD
    stage_and_production.assert_called_once()
    assert stage_and_production.call_args.args[0].flow == PRODUCTION


def test_explicit_source_untested_on_any_flow_refuses_the_set(stage_and_production):
    with pytest.raises(tested.ReleaseSourceRefused) as refused:
        set_source.bind_set_source("platform", [STAGE, PRODUCTION], HEAD)

    assert refused.value.code == tested.UNTESTED
    stage_and_production.assert_not_called()


def test_set_create_binds_once_and_creates_both_runs(stage_and_production):
    made = []

    def create_run_set(project, specs):
        made.extend(specs)
        return [CreatedRun(f"run-{i}", False, "recorded_key") for i, _ in enumerate(specs)]

    def outcome(run_id, **fields):
        from yoke_contracts.api.function_call import HandlerOutcome

        return HandlerOutcome(result_payload={"run_id": run_id, **fields},
                              primary_success=True)

    request = deployment_request(
        function="deployment_runs.create",
        payload={"project": "platform", "flows": [STAGE, PRODUCTION],
                 "idempotency_key": "release"},
    )
    with (
        mock.patch("yoke_core.domain.deployment_run_create_idempotency.replay_run",
                   return_value=None),
        mock.patch("yoke_core.domain.deployment_run_create_write.create_run_set",
                   side_effect=create_run_set),
        mock.patch.object(deployment_run_creation, "_created_outcome", side_effect=outcome),
    ):
        result = deployment_run_creation.handle_deployment_run_create(request)

    assert result.primary_success is True, result.error
    assert [run["run_id"] for run in result.result_payload["runs"]] == ["run-0", "run-1"]
    assert [(s["flow"], s["release_lineage"], s["idempotency_key"]) for s in made] == [
        (STAGE, HEAD, f"release:{STAGE}"),
        (PRODUCTION, HEAD, f"release:{PRODUCTION}"),
    ]
    stage_and_production.assert_called_once()


@pytest.mark.parametrize("extra, field", [
    ({"flow": STAGE}, "flow"),
    ({"environment": "prod"}, "environment"),
    ({"retry_of": "run-1"}, "retry_of"),
    ({"idempotency_key": None}, "idempotency_key"),
])
def test_set_refuses_single_run_fields(extra, field):
    payload = {"project": "platform", "flows": [STAGE, PRODUCTION],
               "idempotency_key": "release", **extra}
    request = deployment_request(function="deployment_runs.create", payload=payload)

    result = deployment_run_creation.handle_deployment_run_create(request)

    assert result.primary_success is False
    assert result.error.code == "payload_invalid"
    assert result.error.jsonpath == f"$.payload.{field}"
