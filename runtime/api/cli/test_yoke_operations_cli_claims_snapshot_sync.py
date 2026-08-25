"""Path-claim write adapters opportunistically sync local snapshots."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _dispatch_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"ok": True},
    )


def _run(*argv: str, requests: list[FunctionCallRequest] | None = None) -> int:
    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        if requests is not None:
            requests.append(request)
        return _dispatch_ok(request)

    with patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch",
        side_effect=dispatch,
    ), patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            return cli_main(list(argv))


# Registering without --allow-planned refuses a path that exists in neither
# tree before it reaches the sync, so proving the ordering needs a real one.
_COMMITTED = "runtime/api/cli/test_yoke_operations_cli_claims_snapshot_sync.py"


def test_register_attempts_snapshot_sync_before_dispatch() -> None:
    with patch(
        "yoke_cli.commands.adapters.claims.sync_local_snapshot_for_write"
    ) as sync:
        rc = _run(
            "claims", "path", "register",
            "--item", "1819",
            "--paths", _COMMITTED,
            "--integration-target", "main",
        )
    assert rc == 0
    sync.assert_called_once_with(
        project=None, integration_target="main", session_id=None,
    )


def test_widen_attempts_snapshot_sync_before_dispatch() -> None:
    with patch(
        "yoke_cli.commands.adapters.claims_path_change."
        "sync_local_snapshot_for_write"
    ) as sync:
        rc = _run(
            "claims", "path", "widen",
            "--claim-id", "273",
            "--add-paths", "src/new.py",
            "--reason", "extend coverage",
            "--item", "1819",
        )
    assert rc == 0
    sync.assert_called_once_with(
        project=None, integration_target=None, session_id=None,
    )


def test_widen_dispatches_full_db_claim_json_atomically() -> None:
    requests: list[FunctionCallRequest] = []
    with patch(
        "yoke_cli.commands.adapters.claims_path_change."
        "sync_local_snapshot_for_write"
    ):
        rc = _run(
            "claims", "path", "widen",
            "--claim-id", "273",
            "--add-paths", "app/db/migrations/0002_add_index.py",
            "--reason", "migration scope discovered",
            "--item", "1819",
            "--db-claim-json",
            '{"state":"declared","model_name":"primary"}',
            requests=requests,
        )

    assert rc == 0
    assert requests[0].payload["db_claim"] == {
        "state": "declared",
        "model_name": "primary",
    }


def test_widen_refuses_non_object_db_claim_json() -> None:
    assert _run(
        "claims", "path", "widen",
        "--claim-id", "273",
        "--add-paths", "app/db/migrations/0002_add_index.py",
        "--reason", "migration scope discovered",
        "--item", "1819",
        "--db-claim-json", "[]",
    ) == 2
