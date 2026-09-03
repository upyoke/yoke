"""Partial-report behavior for failed HTTPS Doctor batches."""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from yoke_cli.commands.adapters.doctor_https_run import dispatch_chunked
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    RUNTIME_LOCAL,
)
from yoke_core.engines.doctor_https_local_scope import (
    requested_local_machine_slugs,
)
from yoke_core.engines.doctor_registry_types import HealthCheck


def _no_op_check(_conn, _args, _rec) -> None:
    return None


def test_failed_relay_local_scope_respects_applicability() -> None:
    local = HealthCheck(
        "local-fix",
        "Local fix",
        _no_op_check,
        applicability=CheckApplicability(
            runtimes=frozenset({RUNTIME_LOCAL}),
        ),
    )
    source = HealthCheck(
        "source-check",
        "Source check",
        _no_op_check,
        applicability=CheckApplicability(requires_source_checkout=True),
    )
    gated = HealthCheck(
        "capability-check",
        "Capability check",
        _no_op_check,
        applicability=CheckApplicability(
            requires_source_checkout=True,
            required_capabilities=("migration_model",),
        ),
    )
    module = "yoke_core.engines.doctor_https_local_scope"
    with (
        patch(f"{module}.HEALTH_CHECKS", [local, source, gated]),
        patch(f"{module}.local_runtime_slugs", return_value={"local-fix"}),
        patch(
            f"{module}.source_checkout_slugs",
            return_value={"source-check", "capability-check"},
        ),
        patch(f"{module}.checkout_root_for_project", return_value=Path("/checkout")),
        patch(f"{module}.is_yoke_source_checkout", return_value=False),
    ):
        runtime, source_tree = requested_local_machine_slugs(
            {
                "project": "external",
                "only": "HC-local-fix,HC-source-check,HC-capability-check",
                "fix": True,
            }
        )

    assert runtime == ["local-fix"]
    assert source_tree == ["source-check"]


def test_transport_failure_runs_local_fixes_and_reports_partial() -> None:
    payload = {
        "project": "yoke",
        "quick": True,
        "full": False,
        "fix": True,
        "runtime": "hosted",
    }
    calls = []

    def _relay(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return FunctionCallResponse(
                success=True,
                function="doctor.run.run",
                version="v1",
                request_id="first",
                result={
                    "results": [
                        {
                            "hc": "HC-first",
                            "name": "Completed remote check",
                            "severity": "PASS",
                            "detail": "",
                        }
                    ],
                    "scope": "quick",
                    "project": "yoke",
                    "runtime": "hosted",
                    "fail_count": 0,
                    "warn_count": 0,
                    "pass_count": 1,
                    "na_count": 0,
                    "done": False,
                    "cursor": "first",
                },
            )
        return FunctionCallResponse(
            success=False,
            function="doctor.run.run",
            version="v1",
            request_id="failed",
            error=FunctionError(
                code="https_transport_failed",
                message="HTTP 503 returned a non-envelope body",
            ),
        )

    local = [
        {
            "hc": "HC-session-relay-orphans",
            "name": "Machine relay orphan sweep",
            "severity": "PASS",
            "detail": "removed one orphan",
        }
    ]
    with (
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.prepare_https_only_payload",
            return_value=(payload, []),
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.https_relay_needed",
            return_value=True,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.requested_local_machine_slugs",
            return_value=(["session-relay-orphans"], []),
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.run_local_runtime_checks",
            return_value=local,
        ) as local_run,
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.machine_has_checkout_for",
            return_value=False,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_run.call_dispatcher",
            side_effect=_relay,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_run.persist_composed_receipt",
        ) as persist,
        redirect_stdout(StringIO()) as stdout,
    ):
        rc = dispatch_chunked(
            payload=payload,
            session_id="test-session",
            json_mode=True,
            chunk_max_checks=1,
            timeout_s=30.0,
        )

    local_run.assert_called_once_with(
        project="yoke",
        quick=True,
        fix=True,
        slugs=["session-relay-orphans"],
    )
    persist.assert_not_called()
    envelope = json.loads(stdout.getvalue())
    assert rc == 1
    assert envelope["success"] is False
    assert envelope["error"]["code"] == "doctor_control_plane_partial"
    result = envelope["result"]
    assert result["partial"] is True
    assert result["completed_control_plane_batches"] == 1
    assert result["control_plane_error"]["code"] == "https_transport_failed"
    assert result["pass_count"] == 2
    assert result["fail_count"] == 1
    assert [row["hc"] for row in result["results"]] == [
        "HC-first",
        "HC-session-relay-orphans",
        "HC-doctor-control-plane-batch",
    ]


def test_transport_partial_human_output_includes_report_and_recovery() -> None:
    failed = FunctionCallResponse(
        success=False,
        function="doctor.run.run",
        version="v1",
        request_id="failed",
        result={"results": [], "scope": "quick", "project": "yoke"},
        error=FunctionError(
            code="https_transport_failed",
            message="HTTP 503 returned a non-envelope body",
        ),
    )
    with (
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.prepare_https_only_payload",
            side_effect=lambda value: (value, []),
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.https_relay_needed",
            return_value=True,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.requested_local_machine_slugs",
            return_value=([], []),
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.machine_has_checkout_for",
            return_value=False,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_run.collect_chunked",
            return_value=failed,
        ),
        redirect_stdout(StringIO()) as stdout,
        redirect_stderr(StringIO()) as stderr,
    ):
        rc = dispatch_chunked(
            payload={"project": "yoke", "quick": True, "fix": True},
            session_id="test-session",
            json_mode=False,
            chunk_max_checks=1,
            timeout_s=30.0,
        )

    assert rc == 1
    # Human mode renders the partial report it did manage to collect, and
    # names the failure and its recovery on stderr rather than swallowing
    # either behind a raw payload dump.
    assert stdout.getvalue().startswith("# Ouroboros Health Report")
    assert "doctor_control_plane_partial" in stderr.getvalue()
    assert "Retry the same `yoke doctor run`" in stderr.getvalue()
