"""Transport contract for ``yoke github merge-queue apply``."""

from __future__ import annotations

import io
import json
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_core.domain.handlers.github_merge_queue_apply import (
    handle_merge_queue_apply,
)


def _declaration() -> dict:
    return {
        "schema": 1,
        "ruleset": {
            "name": "merge-queue-main",
            "rules": [{"type": "merge_queue", "parameters": {}}],
        },
        "repository": {"allow_auto_merge": True},
    }


@pytest.mark.parametrize("explicit_path", (False, True))
def test_https_apply_transports_declaration_content(
    tmp_path: Path,
    explicit_path: bool,
) -> None:
    declaration_path = tmp_path / ".yoke" / "merge-queue.json"
    declaration_path.parent.mkdir()
    declaration_path.write_text(json.dumps(_declaration()), encoding="utf-8")
    captured: list[FunctionCallRequest] = []
    apply = Mock(
        return_value={
            "preview": True,
            "owner": "upyoke",
            "repo": "yoke",
            "ruleset_name": "merge-queue-main",
            "ruleset_id": 42,
            "actions": [],
            "changed": False,
            "drift_before": [],
            "remaining_drift": [],
        }
    )

    def relay(
        request: FunctionCallRequest,
        *_args,
        **_kwargs,
    ) -> FunctionCallResponse:
        captured.append(request)
        outcome = handle_merge_queue_apply(request)
        return FunctionCallResponse(
            success=outcome.primary_success,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=outcome.result_payload,
            error=outcome.error,
        )

    argv = [
        "github",
        "merge-queue",
        "apply",
        "--project",
        "yoke",
        "--preview",
        "--json",
    ]
    if explicit_path:
        argv.extend(("--declaration", str(declaration_path)))

    stdout = io.StringIO()
    stderr = io.StringIO()
    with ExitStack() as stack:
        stack.enter_context(
            patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"})
        )
        stack.enter_context(
            patch(
                "yoke_cli.commands.adapters.github_merge_queue."
                "resolve_repo_root_from_cwd",
                return_value=str(tmp_path),
            )
        )
        stack.enter_context(patch("yoke_cli.commands._helpers.ensure_handlers_loaded"))
        stack.enter_context(
            patch(
                "yoke_cli.transport.dispatcher.https_transport."
                "resolve_https_connection",
                return_value=HttpsConnection(
                    api_url="https://control.example.test",
                    token="test-token",
                ),
            )
        )
        stack.enter_context(
            patch(
                "yoke_cli.transport.dispatcher.https_transport.relay_https",
                side_effect=relay,
            )
        )
        stack.enter_context(
            patch(
                "yoke_core.domain.project_github_auth.resolve_project_github_auth",
                return_value=SimpleNamespace(
                    repo="upyoke/yoke",
                    token="github-token",
                ),
            )
        )
        stack.enter_context(
            patch(
                "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
                side_effect=AssertionError(
                    "remote control plane must not read the client checkout"
                ),
            )
        )
        stack.enter_context(
            patch(
                "yoke_core.domain.merge_queue_declaration_apply.apply_declaration",
                apply,
            )
        )
        stack.enter_context(redirect_stdout(stdout))
        stack.enter_context(redirect_stderr(stderr))
        rc = cli_main(argv)

    assert rc == 0, stderr.getvalue()
    assert len(captured) == 1
    assert captured[0].payload == {
        "project": "yoke",
        "preview": True,
        "declaration": _declaration(),
    }
    apply.assert_called_once_with(
        _declaration(),
        owner="upyoke",
        repo="yoke",
        token="github-token",
        preview=True,
    )
    assert json.loads(stdout.getvalue())["result"]["changed"] is False


def test_invalid_local_json_fails_before_https_dispatch(tmp_path: Path) -> None:
    declaration_path = tmp_path / "merge-queue.json"
    declaration_path.write_text("{", encoding="utf-8")
    relay = Mock()

    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch("yoke_cli.transport.dispatcher.https_transport.relay_https", relay),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        rc = cli_main(
            [
                "github",
                "merge-queue",
                "apply",
                "--project",
                "yoke",
                "--declaration",
                str(declaration_path),
            ]
        )

    assert rc == 2
    relay.assert_not_called()


def test_readiness_cli_dispatches_the_item_scoped_read() -> None:
    with patch(
        "yoke_cli.commands.adapters.github_merge_queue.dispatch_and_emit",
        return_value=0,
    ) as dispatch:
        rc = cli_main(["github", "merge-queue", "readiness", "YOK-2842", "--json"])

    assert rc == 0
    call = dispatch.call_args.kwargs
    assert call["function_id"] == "github.merge_queue.readiness"
    assert call["target"].public_ref == "YOK-2842"
    assert call["payload"] == {}
