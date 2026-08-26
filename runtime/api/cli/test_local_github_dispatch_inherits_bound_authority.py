"""In-process dispatch inherits the GitHub user authority its caller bound.

The merge child pins its machine user-token provider to the https plane it
was connected to, then selects that plane's owner-only admin connection for
its engine. A dispatch inside that child that rebound a provider from the
ambient connection proved against "local Yoke" instead, where a
service-bound profile can never authorize — so every close-out sync under
the admin connection refused while the merge itself had already landed.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from runtime.api.cli.test_github_app_machine_security import (
    _profile_opener,
    _refresh_opener,
)
from runtime.api.cli.test_github_status_merge_path_binding import (
    ADMIN_ENV,
    _admin_sibling_machine,
)
from yoke_cli.commands import merge_item_local_runtime as local_runtime
from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_machine_operation
from yoke_cli.config import github_oauth_transport
from yoke_cli.transport import local_github_dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import project_github_auth
from yoke_core.domain import standalone_item_merge
from yoke_core.domain import yoke_function_dispatch
from yoke_core.domain.github_app_dispatch_context import LOCAL_USER_TOKEN_PROVIDER
from yoke_core.domain.project_github_auth_models import (
    GITHUB_AUTHORITY_USER,
    MissingAppCredentials,
    ProjectGithubAuthError,
    ProjectGithubState,
)


GITHUB_API_URL = "https://api.github.com"


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.github_sync",
        actor=ActorContext(session_id="s-1"),
        target=TargetRef(kind="item", item_id=42),
    )


def _ok(request: FunctionCallRequest) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={},
    )


def test_dispatch_inside_a_bound_authority_inherits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_OVERRIDE, ADMIN_ENV)
    monkeypatch.setattr(
        local_github_dispatch.machine_config,
        "github_config",
        lambda *_args, **_kwargs: pytest.fail(
            "a bound authority must not be replaced by an ambient one"
        ),
    )
    lock_calls: list[int] = []

    @contextmanager
    def tracking_lock(*_args, **_kwargs):
        lock_calls.append(1)
        yield

    monkeypatch.setattr(github_machine_operation, "operation_lock", tracking_lock)
    seen: dict[str, str] = {}

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        provider = LOCAL_USER_TOKEN_PROVIDER.get()
        assert provider is not None
        seen["token"] = provider()
        return _ok(request)

    with project_github_auth.bind_local_github_user_token_provider(
        lambda: "ghu_pinned", api_url=GITHUB_API_URL,
    ):
        response = local_github_dispatch.call_with_machine_github_authorization(
            _request(), dispatch, core_available=True,
        )

    assert response.success is True
    assert seen["token"] == "ghu_pinned"
    assert lock_calls == []


def _bound_state() -> ProjectGithubState:
    return ProjectGithubState(
        project_slug="yoke",
        project_id=1,
        has_capability=True,
        binding={
            "status": "active",
            "github_repo": "upyoke/yoke",
            "installation_id": "12345",
            "repository_id": "4567",
            "api_url": GITHUB_API_URL,
        },
        installation={
            "status": "active",
            "permissions": json.dumps(
                dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS)
            ),
            "api_url": GITHUB_API_URL,
        },
    )


def _engine_resolving_project_auth(
    seen: dict[str, Any],
) -> Callable[[FunctionCallRequest], FunctionCallResponse]:
    """The sync handler's auth-first read, run by the real resolver."""

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        try:
            resolved = project_github_auth.resolve_project_github_auth("yoke")
        except ProjectGithubAuthError as exc:
            return FunctionCallResponse(
                success=False,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                error=FunctionError(
                    code=exc.code,
                    message=f"sync_item short-circuit: {type(exc).__name__}: {exc}",
                ),
            )
        seen["token"] = resolved.token
        seen["token_source"] = resolved.token_source
        return _ok(request)

    return dispatch


def test_merge_child_close_out_sync_proves_through_the_pinned_plane(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The close-out sync reads the token the merge child pinned, not an ambient one.

    Every network edge is the plane and GitHub answering as they do on a
    healthy machine; the engine is the real resolver on a workstation that
    holds no service App key, so only the machine user authorization can
    answer — and under the admin connection it only answers through the
    pinned plane.
    """
    _admin_sibling_machine(tmp_path, monkeypatch)
    monkeypatch.setattr(github_app_public_profile, "_urlopen", _profile_opener)
    monkeypatch.setattr(github_oauth_transport, "_urlopen", _refresh_opener)
    monkeypatch.setattr(
        project_github_auth, "read_github_state", lambda *_a, **_k: _bound_state(),
    )
    monkeypatch.setattr(
        project_github_auth, "register_installation_token", lambda *_a, **_k: None,
    )

    def _no_service_key(state, _config):
        raise MissingAppCredentials(
            state.project_slug,
            "GitHub App control-plane credentials are unavailable",
        )

    monkeypatch.setattr(project_github_auth, "read_app_credentials", _no_service_key)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        yoke_function_dispatch, "dispatch", _engine_resolving_project_auth(seen),
    )
    monkeypatch.setattr(
        local_runtime,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=True,
            result={"holder": {
                "target_kind": "item", "scope": {"item_id": 42},
                "session_id": "session-1",
            }},
            error=None,
        ),
    )

    def child_main(argv: list[str]) -> int:
        assert os.environ.get(ENV_OVERRIDE) == ADMIN_ENV
        seen["sync_error"] = standalone_item_merge.sync_item_to_github(42)
        return 0

    real_import = local_runtime.importlib.import_module

    def import_module(name: str):
        if name == "yoke_core.domain.standalone_item_merge_cli":
            return SimpleNamespace(main=child_main)
        return real_import(name)

    monkeypatch.setattr(local_runtime.importlib, "import_module", import_module)

    assert local_runtime.run(["YOK-42", "--session-id", "session-1"]) == 0

    assert seen["sync_error"] is None
    assert seen["token"] == "refreshed-access"
    assert seen["token_source"] == GITHUB_AUTHORITY_USER
    assert LOCAL_USER_TOKEN_PROVIDER.get() is None
