"""CLI envelope contract for release-pin record."""

from __future__ import annotations

import io
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.commands.adapters.release_pin_verify import release_pin_verify
from yoke_cli.commands.release_pin_agreement import PinHealthAgreement
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(*argv: str, transport: str = "local-postgres"):
    captured = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "project": "customer-app",
                "environment": "canary",
                "environment_id": "customer-canary",
                "settings_path": "delivery.component_pin",
                "pin": "build-43",
                "changed": True,
            },
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with ExitStack() as stack:
        stack.enter_context(
            patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"})
        )
        stack.enter_context(patch("yoke_cli.commands._helpers.ensure_handlers_loaded"))
        if transport == "https":
            stack.enter_context(
                patch(
                    "yoke_cli.transport.dispatcher.https_transport.resolve_https_connection",
                    return_value=HttpsConnection(
                        api_url="https://control.example.test",
                        token="test-token",
                    ),
                )
            )
            stack.enter_context(
                patch(
                    "yoke_cli.transport.dispatcher.https_transport.relay_https",
                    side_effect=lambda request, *_args, **_kwargs: dispatch(request),
                )
            )
        else:
            stack.enter_context(
                patch(
                    "yoke_cli.transport.dispatcher.https_transport.resolve_https_connection",
                    return_value=None,
                )
            )
            stack.enter_context(
                patch(
                    "yoke_core.domain.yoke_function_dispatch.dispatch",
                    side_effect=dispatch,
                )
            )
        stack.enter_context(redirect_stdout(stdout))
        stack.enter_context(redirect_stderr(stderr))
        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue(), captured


def test_record_dispatches_only_project_target_and_release_inputs():
    rc, out, _err, calls = _run(
        "release-pin",
        "record",
        "--project",
        "customer-app",
        "--environment",
        "canary",
        "--pin",
        "build-43",
    )

    assert rc == 0
    assert out == "customer-app|canary|build-43|changed\n"
    request = calls[0]
    assert request.function == "release_pin.record"
    assert request.target.kind == "global"
    assert request.target.project_id == "customer-app"
    assert request.payload == {
        "project": "customer-app",
        "environment": "canary",
        "pin": "build-43",
    }


@pytest.mark.parametrize("transport", ("local-postgres", "https"))
def test_record_uses_the_same_envelope_across_transports(transport):
    rc, _out, _err, calls = _run(
        "release-pin",
        "record",
        "--project",
        "customer-app",
        "--environment",
        "canary",
        "--pin",
        "build-43",
        transport=transport,
    )

    assert rc == 0
    assert len(calls) == 1
    assert calls[0].target.project_id == "customer-app"
    assert calls[0].payload == {
        "project": "customer-app",
        "environment": "canary",
        "pin": "build-43",
    }


def test_record_requires_project_environment_and_pin():
    rc, _out, _err, calls = _run("release-pin", "record", "--project", "customer-app")

    assert rc == 2
    assert calls == []


def test_record_is_registered_as_a_dispatcher_backed_surface():
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    function_id, _adapter = SUBCOMMAND_REGISTRY[("release-pin", "record")]
    assert function_id == "release_pin.record"


def test_verify_reads_the_complete_capability_configured_probe_contract():
    observed = {}

    def environment_values(project, environment_id, paths, session_id):
        observed.update(
            project=project,
            environment_id=environment_id,
            paths=paths,
            session_id=session_id,
        )
        return {
            "delivery.component_pin": "build-43",
            "monitoring.status_url": "https://service.example.test/status",
        }

    def evaluate(**kwargs):
        observed["agreement"] = kwargs
        return PinHealthAgreement(
            agreed=True,
            desired_pin="build-43",
            served_pin="build-43",
        )

    with (
        patch(
            "yoke_cli.commands.adapters.release_pin_verify._capability_settings",
            return_value={
                "environment_by_target": {"canary": "customer-canary"},
                "desired_pin_path": "delivery.component_pin",
                "probe_url_path": "monitoring.status_url",
                "served_pin_response_path": "build.release",
            },
        ),
        patch(
            "yoke_cli.commands.adapters.release_pin_verify._environment_values",
            side_effect=environment_values,
        ),
        patch(
            "yoke_cli.commands.adapters.release_pin_verify.evaluate_pin_health_agreement",
            side_effect=evaluate,
        ),
    ):
        assert (
            release_pin_verify(["--project", "customer-app", "--environment", "canary"])
            == 0
        )

    assert observed["environment_id"] == "customer-canary"
    assert observed["paths"] == [
        "delivery.component_pin",
        "monitoring.status_url",
    ]
    assert observed["agreement"] == {
        "desired_pin": "build-43",
        "probe_url": "https://service.example.test/status",
        "desired_path": "delivery.component_pin",
        "probe_url_path": "monitoring.status_url",
        "served_pin_response_path": "build.release",
    }


@pytest.mark.parametrize(
    "missing_key",
    ("desired_pin_path", "probe_url_path", "served_pin_response_path"),
)
def test_verify_refuses_an_incomplete_capability(missing_key):
    settings = {
        "environment_by_target": {"canary": "customer-canary"},
        "desired_pin_path": "delivery.component_pin",
        "probe_url_path": "monitoring.status_url",
        "served_pin_response_path": "build.release",
    }
    settings.pop(missing_key)
    with patch(
        "yoke_cli.commands.adapters.release_pin_verify._capability_settings",
        return_value=settings,
    ):
        assert (
            release_pin_verify(["--project", "customer-app", "--environment", "canary"])
            == 2
        )
