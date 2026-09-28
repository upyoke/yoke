"""CLI output for keyed deployment-run creation."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)

RUN_ID = "run-20260928-006"


def _create(result: dict, *argv: str, error: FunctionError | None = None):
    captured: list[FunctionCallRequest] = []

    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=error is None,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
            error=error,
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch("yoke_core.domain.yoke_function_dispatch.dispatch", side_effect=stub):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main(["deployment-runs", "create", "yoke", "flow", *argv])
    return rc, out.getvalue(), err.getvalue(), captured


def test_create_requires_an_idempotency_key() -> None:
    rc, _out, err, captured = _create({})

    assert rc == 2
    assert "--idempotency-key" in err
    assert captured == []


def test_create_sends_the_key() -> None:
    result = {"run_id": RUN_ID, "idempotency_key": "k1", "replayed": False}
    rc, out, err, captured = _create(result, "--idempotency-key", "k1")

    assert rc == 0, err
    assert out.strip() == RUN_ID
    assert captured[0].payload["idempotency_key"] == "k1"
    assert "already created" not in err


def test_replay_prints_the_original_run_and_says_so() -> None:
    result = {"run_id": RUN_ID, "idempotency_key": "k1", "replayed": True}
    rc, out, err, _captured = _create(result, "--idempotency-key", "k1")

    assert rc == 0, err
    assert out.strip() == RUN_ID
    assert f"'k1' already created {RUN_ID}" in err


def test_server_without_keyed_create_warns_that_a_repeat_is_unsafe() -> None:
    rc, out, err, _captured = _create(
        {"run_id": RUN_ID, "status": "created"}, "--idempotency-key", "k1"
    )

    assert rc == 0, err
    assert out.strip() == RUN_ID
    assert "predates idempotent create" in err
    assert "WILL mint another run" in err


def test_conflict_refusal_is_printed_by_name() -> None:
    rc, _out, err, _captured = _create(
        {},
        "--idempotency-key",
        "k1",
        error=FunctionError(
            code="idempotency_key_conflict",
            message=f"idempotency key 'k1' already created {RUN_ID} from a different request",
        ),
    )

    assert rc != 0
    assert "idempotency_key_conflict" in err
    assert RUN_ID in err
