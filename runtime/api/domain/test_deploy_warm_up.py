"""The warm-up gate pays the rolled box's cold start before a run succeeds.

That a project's own live routes actually place a warm-up after the roll
is checked against the flow rows by ``HC-hosted-route-stage-contract``.
"""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import deploy_warm_up
from yoke_core.domain import deploy_pipeline_step_runners
from yoke_core.domain.flow_validation import validate_stages
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


class _Connection:
    api_url = "https://app.example.com/api/orgs/acme"
    token = "t"
    env = "prod"


def _response(success: bool, error: FunctionError | None = None):
    return FunctionCallResponse(
        success=success,
        function=deploy_warm_up.DEFAULT_WARM_UP_FUNCTION,
        version="v1",
        request_id="r",
        error=error,
    )


def _clock(*readings: float):
    return mock.patch.object(deploy_warm_up, "_monotonic", side_effect=readings)


class TestWarmUpEnvironment:
    def test_successful_call_reports_measured_latency(self):
        with mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_Connection(),
        ), mock.patch(
            "yoke_cli.transport.https.relay_https",
            return_value=_response(True),
        ) as relay, _clock(10.0, 51.5):
            outcome = deploy_warm_up.warm_up_environment("prod")

        assert outcome.ok is True
        assert outcome.connection_env == "prod"
        assert outcome.function_id == deploy_warm_up.DEFAULT_WARM_UP_FUNCTION
        assert outcome.latency_ms == 41500
        assert "41500ms" in outcome.detail
        request, connection = relay.call_args.args
        assert request.function == deploy_warm_up.DEFAULT_WARM_UP_FUNCTION
        assert request.target.kind == "global"
        assert connection is not None
        assert (
            relay.call_args.kwargs["timeout_s"]
            == deploy_warm_up.DEFAULT_WARM_UP_TIMEOUT_S
        )

    def test_timeout_is_generously_past_the_client_relay_ceiling(self):
        from yoke_cli.transport.https import _DEFAULT_TIMEOUT_S

        assert deploy_warm_up.DEFAULT_WARM_UP_TIMEOUT_S > _DEFAULT_TIMEOUT_S

    def test_stage_config_overrides_function_and_timeout(self):
        with mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_Connection(),
        ), mock.patch(
            "yoke_cli.transport.https.relay_https",
            return_value=_response(True),
        ) as relay, _clock(0.0, 1.0):
            outcome = deploy_warm_up.warm_up_environment(
                "stage", function_id="items.list", timeout_s=42.0,
            )

        assert outcome.ok is True
        assert relay.call_args.args[0].function == "items.list"
        assert relay.call_args.kwargs["timeout_s"] == 42.0

    def test_failed_call_carries_the_real_error_and_latency(self):
        error = FunctionError(
            code="https_transport_failed",
            message="relay did not answer",
        )
        with mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_Connection(),
        ), mock.patch(
            "yoke_cli.transport.https.relay_https",
            return_value=_response(False, error),
        ), _clock(0.0, 180.0):
            outcome = deploy_warm_up.warm_up_environment("prod")

        assert outcome.ok is False
        assert outcome.latency_ms == 180000
        assert "https_transport_failed" in outcome.detail
        assert "relay did not answer" in outcome.detail

    def test_non_https_connection_refuses_and_never_relays(self):
        with mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=None,
        ), mock.patch("yoke_cli.transport.https.relay_https") as relay:
            outcome = deploy_warm_up.warm_up_environment("local")

        assert outcome.ok is False
        assert "not an https relay target" in outcome.detail
        assert "yoke connection set local" in outcome.detail
        relay.assert_not_called()

    def test_misconfigured_connection_reports_the_transport_error(self):
        from yoke_cli.transport.https import TransportError

        with mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            side_effect=TransportError("token file is empty"),
        ):
            outcome = deploy_warm_up.warm_up_environment("prod")

        assert outcome.ok is False
        assert "token file is empty" in outcome.detail

    def test_missing_connection_env_names_what_the_stage_must_declare(self):
        outcome = deploy_warm_up.warm_up_environment("  ")

        assert outcome.ok is False
        assert "connection_env" in outcome.detail


class TestWarmUpStageDispatch:
    def _dispatch(self, stage_config):
        return deploy_pipeline_step_runners._dispatch_step_runner(
            {
                "name": "warm-up",
                "step_runner": "warm-up",
                "config": {"step_runner": "warm-up", **stage_config},
            },
            run_id="run-1",
            member_items=["7"],
            github_repo="o/r",
            project="yoke",
            project_repo_path="/repo",
            branch="b",
            first_item="7",
            timeout_min=1,
            fresh=False,
            environment_name="prod",
            gate_branch="main",
            release_lineage="a" * 40,
        )

    def test_warm_stage_passes_and_records_the_call_on_the_run(self):
        outcome = deploy_warm_up.WarmUpOutcome(
            ok=True,
            connection_env="prod",
            function_id="board.data.get",
            latency_ms=37000,
            detail="board.data.get answered prod in 37000ms",
        )
        with mock.patch.object(
            deploy_warm_up, "warm_up_environment", return_value=outcome,
        ) as warm, mock.patch.object(
            deploy_pipeline_step_runners, "emit_run_event",
        ) as emit:
            rc, diag = self._dispatch({"connection_env": "prod"})

        assert (rc, diag) == (0, "")
        warm.assert_called_once_with(
            "prod",
            function_id=deploy_warm_up.DEFAULT_WARM_UP_FUNCTION,
            timeout_s=deploy_warm_up.DEFAULT_WARM_UP_TIMEOUT_S,
        )
        name, result, context = emit.call_args.args
        assert (name, result) == ("DeploymentRunWarmedUp", "completed")
        assert context == {
            "run_id": "run-1",
            "connection_env": "prod",
            "function": "board.data.get",
            "latency_ms": 37000,
        }
        assert emit.call_args.kwargs["member_items"] == ["7"]

    def test_cold_box_fails_the_stage_with_the_real_error(self):
        outcome = deploy_warm_up.WarmUpOutcome(
            ok=False,
            connection_env="prod",
            function_id="board.data.get",
            latency_ms=180000,
            detail="board.data.get failed against prod after 180000ms",
        )
        with mock.patch.object(
            deploy_warm_up, "warm_up_environment", return_value=outcome,
        ), mock.patch.object(
            deploy_pipeline_step_runners, "emit_run_event",
        ) as emit:
            rc, diag = self._dispatch({"connection_env": "prod"})

        assert rc == 1
        assert diag == outcome.detail
        emit.assert_not_called()


class TestWarmUpStageVocabulary:
    def test_stage_vocabulary_accepts_a_warm_up_stage(self):
        validate_stages(json.dumps([
            {"name": "warm-up", "step_runner": "warm-up",
             "connection_env": "prod"},
        ]))
