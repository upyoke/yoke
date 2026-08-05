"""CLI envelope contract for release-pin record."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_cli.commands.adapters.release_pin_verify import release_pin_verify
from yoke_cli.commands.release_pin_agreement import PinHealthAgreement
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(*argv: str):
    captured = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "project": "platform",
                "environment": "stage",
                "environment_id": "service-stage",
                "settings_path": "release.component_pin",
                "pin": "0.1.1+launch.188",
                "changed": True,
            },
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue(), captured


def test_record_dispatches_only_project_target_and_release_inputs():
    rc, out, _err, calls = _run(
        "release-pin",
        "record",
        "--project",
        "platform",
        "--environment",
        "stage",
        "--pin",
        "0.1.1+launch.188",
    )

    assert rc == 0
    assert out == "platform|stage|0.1.1+launch.188|changed\n"
    request = calls[0]
    assert request.function == "release_pin.record"
    assert request.target.kind == "global"
    assert request.target.project_id == "platform"
    assert request.payload == {
        "project": "platform",
        "environment": "stage",
        "pin": "0.1.1+launch.188",
    }


def test_record_requires_project_environment_and_pin():
    rc, _out, _err, calls = _run(
        "release-pin", "record", "--project", "platform"
    )

    assert rc == 2
    assert calls == []


def test_record_is_registered_as_a_dispatcher_backed_surface():
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    function_id, _adapter = SUBCOMMAND_REGISTRY[("release-pin", "record")]
    assert function_id == "release_pin.record"


def test_verify_reads_the_capability_configured_desired_path():
    observed = {}

    def environment_values(project, environment_id, paths, session_id):
        observed.update(
            project=project,
            environment_id=environment_id,
            paths=paths,
            session_id=session_id,
        )
        return {
            "delivery.component_pin": "0.1.1+launch.188",
            "release.health_probe_url": "https://example.test/health",
        }

    with (
        patch(
            "yoke_cli.commands.adapters.release_pin_verify._capability_settings",
            return_value={
                "environment_by_target": {"stage": "service-stage"},
                "desired_pin_path": "delivery.component_pin",
            },
        ),
        patch(
            "yoke_cli.commands.adapters.release_pin_verify._environment_values",
            side_effect=environment_values,
        ),
        patch(
            "yoke_cli.commands.adapters.release_pin_verify.evaluate_pin_health_agreement",
            return_value=PinHealthAgreement(agreed=True),
        ),
    ):
        assert release_pin_verify(
            ["--project", "platform", "--environment", "stage"]
        ) == 0

    assert observed["environment_id"] == "service-stage"
    assert observed["paths"] == [
        "delivery.component_pin",
        "release.health_probe_url",
    ]


def test_verify_refuses_a_legacy_capability_without_desired_path():
    with patch(
        "yoke_cli.commands.adapters.release_pin_verify._capability_settings",
        return_value={"environment_by_target": {"stage": "service-stage"}},
    ):
        assert release_pin_verify(
            ["--project", "platform", "--environment", "stage"]
        ) == 2
