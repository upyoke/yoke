"""CLI trigger names recovered vs freshly posted workflow runs."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List
from unittest.mock import patch

from yoke_cli.commands.adapters import github_actions_workflow as workflow_mod
from yoke_cli.main import main as cli_main
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_DISPATCHED_MARKER,
    WORKFLOW_DISPATCH_RECOVERED_MARKER,
)


_CAPTURED: List[FunctionCallRequest] = []
_CONNECTION = HttpsConnection(
    api_url="https://control.example",
    token="test-token",
    env="prod",
)


def _run(*, result: Dict[str, Any]) -> tuple[int, str, str]:
    _CAPTURED.clear()

    def relay(
        request: FunctionCallRequest,
        connection: HttpsConnection,
        **_transport_kwargs: object,
    ) -> FunctionCallResponse:
        assert connection == _CONNECTION
        _CAPTURED.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=dict(result),
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch.object(workflow_mod, "ensure_handlers_loaded"), patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_CONNECTION,
        ), patch(
            "yoke_cli.transport.https.relay_https",
            side_effect=relay,
        ):
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(
                io.StringIO()
            ) as err:
                rc = cli_main([
                    "github-actions", "trigger",
                    "upyoke/platform", "deploy.yml",
                    "--request-id", "deploy:yoke:run-1:hosted-release",
                    "--correlation-input", "yoke_dispatch_id",
                    "--project", "yoke",
                ])
    return rc, out.getvalue(), err.getvalue()


def test_trigger_stderr_names_recovered_existing_run() -> None:
    rc, out, err = _run(result={
        "run_id": "32434951903",
        "dispatched": False,
    })
    assert rc == 0
    assert out == "32434951903\n"
    assert WORKFLOW_DISPATCH_RECOVERED_MARKER in err
    assert WORKFLOW_DISPATCH_DISPATCHED_MARKER not in err


def test_trigger_stderr_names_fresh_dispatch() -> None:
    rc, out, err = _run(result={
        "run_id": "4455",
        "dispatched": True,
    })
    assert rc == 0
    assert out == "4455\n"
    assert WORKFLOW_DISPATCH_DISPATCHED_MARKER in err
    assert WORKFLOW_DISPATCH_RECOVERED_MARKER not in err
