"""Local in-process dispatch takes the machine GitHub lock only for tokens."""

from __future__ import annotations

from contextlib import contextmanager

from yoke_cli.config import github_machine_operation
from yoke_cli.config import machine_config
from yoke_cli.transport import local_github_dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.detail.get",
        actor=ActorContext(session_id="s-1"),
        target=TargetRef(kind="item", public_ref="YOK-1"),
    )


def _ok(request: FunctionCallRequest) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={},
    )


def test_credential_free_dispatch_does_not_take_the_machine_lock(
    monkeypatch,
) -> None:
    lock_calls: list[int] = []

    @contextmanager
    def tracking_lock(*_args, **_kwargs):
        lock_calls.append(1)
        yield

    monkeypatch.setattr(github_machine_operation, "operation_lock", tracking_lock)
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda: {"api_url": "https://api.github.com"},
    )

    response = local_github_dispatch.call_with_machine_github_authorization(
        _request(),
        _ok,
        core_available=True,
    )

    assert response.success is True
    assert lock_calls == []


def test_token_read_takes_the_machine_lock_through_access_token(
    monkeypatch,
) -> None:
    lock_calls: list[int] = []

    @contextmanager
    def tracking_lock(*_args, **_kwargs):
        lock_calls.append(1)
        yield

    monkeypatch.setattr(github_machine_operation, "operation_lock", tracking_lock)
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda: {"api_url": "https://api.github.com"},
    )

    class _Token:
        access_token = "ghu_test"

    def fake_access_token(*_args, **_kwargs):
        with github_machine_operation.operation_lock():
            return _Token()

    import yoke_cli.config.github_local_user_access as access_mod

    monkeypatch.setattr(access_mod, "access_token", fake_access_token)

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        from yoke_core.domain.github_app_dispatch_context import (
            LOCAL_USER_TOKEN_PROVIDER,
        )

        provider = LOCAL_USER_TOKEN_PROVIDER.get()
        assert provider is not None
        assert provider() == "ghu_test"
        return _ok(request)

    response = local_github_dispatch.call_with_machine_github_authorization(
        _request(),
        dispatch,
        core_available=True,
    )

    assert response.success is True
    assert lock_calls == [1]
