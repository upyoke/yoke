"""``organizations.create``: the CLI request shape and the engine refusal.

Platform answers this function on a hosted connection; a universe engine
refuses it everywhere with the recovery named.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_contracts.api_urls import HOSTED_PLATFORM_URL
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)

from yoke_core.domain.handlers.organizations_create import (
    ORGANIZATION_CREATE_HOSTED_ONLY,
    handle_organizations_create,
)


def test_engine_refuses_with_hosted_recovery():
    outcome = handle_organizations_create(
        FunctionCallRequest(
            function="organizations.create",
            actor=ActorContext(session_id="handler-test-session"),
            target=TargetRef(kind="global"),
            payload={"name": "Acme"},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == ORGANIZATION_CREATE_HOSTED_ONLY
    assert f"yoke setup --connect {HOSTED_PLATFORM_URL}" in outcome.error.message


def test_cli_sends_name_and_slug():
    captured: list[FunctionCallRequest] = []

    def _stub(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={"org": {"slug": "acme"}},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out = io.StringIO()
                with redirect_stdout(out), redirect_stderr(io.StringIO()):
                    rc = cli_main(
                        ["organizations", "create", "Acme Robotics", "--slug", "acme"]
                    )
    assert rc == 0
    assert captured[0].function == "organizations.create"
    assert captured[0].payload == {"name": "Acme Robotics", "slug": "acme"}
    assert '"slug": "acme"' in out.getvalue()
