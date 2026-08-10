"""HTTPS doctor dispatch honors caller-checkout project-local --only slugs."""

from __future__ import annotations

import json
from io import StringIO
from contextlib import redirect_stdout
from unittest.mock import patch

from yoke_cli.commands.adapters.doctor_https_run import dispatch_chunked
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


def test_https_only_checkout_declared_slug_skips_relayed_validation() -> None:
    """A checkout-declared project-local slug must not hit server only= validation."""
    local_result = {
        "results": [{
            "hc": "HC-shipped-doctrine-path-portability",
            "name": "Shipped doctrine",
            "severity": "PASS",
            "detail": "",
        }],
        "scope": "only",
        "project": "yoke",
        "runtime": "hosted",
        "fail_count": 0,
        "warn_count": 0,
        "pass_count": 1,
        "na_count": 0,
        "composed": "local_project_checks",
    }
    captured: list[dict] = []

    def _forbid_relay(**_kwargs):
        raise AssertionError("checkout-declared only= must not relay")

    with (
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.prepare_https_only_payload",
            return_value=({"project": "yoke", "quick": False, "full": False}, [
                "shipped-doctrine-path-portability",
            ]),
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.https_relay_needed",
            return_value=False,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.local_project_only_result",
            return_value=local_result,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_run.collect_chunked",
            side_effect=_forbid_relay,
        ),
        redirect_stdout(StringIO()) as stdout,
    ):
        rc = dispatch_chunked(
            payload={
                "project": "yoke",
                "only": "HC-shipped-doctrine-path-portability",
                "quick": False,
                "full": False,
                "fix": False,
                "runtime": "hosted",
            },
            session_id="test-session",
            json_mode=True,
            chunk_max_checks=1,
            timeout_s=30.0,
        )
        captured.append(json.loads(stdout.getvalue()))

    assert rc == 0
    envelope = captured[0]
    assert envelope["success"] is True
    assert envelope["result"]["composed"] == "local_project_checks"
    assert [
        row["hc"] for row in envelope["result"]["results"]
    ] == ["HC-shipped-doctrine-path-portability"]


def test_https_only_still_relays_unknown_slug() -> None:
    relay_error = FunctionCallResponse(
        success=False,
        function="doctor.run.run",
        version="v1",
        request_id="r1",
        error=FunctionError(
            code="invalid_check",
            message="unknown HC slug(s): HC-not-a-real-check",
        ),
    )

    with (
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.prepare_https_only_payload",
            return_value=({
                "project": "yoke",
                "only": "HC-not-a-real-check",
                "quick": False,
                "full": False,
            }, []),
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_compose.https_relay_needed",
            return_value=True,
        ),
        patch(
            "yoke_cli.commands.adapters.doctor_https_run.collect_chunked",
            return_value=relay_error,
        ),
        redirect_stdout(StringIO()) as stdout,
    ):
        rc = dispatch_chunked(
            payload={
                "project": "yoke",
                "only": "HC-not-a-real-check",
                "quick": False,
                "full": False,
                "fix": False,
                "runtime": "hosted",
            },
            session_id="test-session",
            json_mode=True,
            chunk_max_checks=1,
            timeout_s=30.0,
        )
        envelope = json.loads(stdout.getvalue())

    assert rc == 1
    assert envelope["success"] is False
    assert envelope["error"]["code"] == "invalid_check"
