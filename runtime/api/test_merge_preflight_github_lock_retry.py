"""Merge preflight reads retry only the transient machine GitHub lock."""

from types import SimpleNamespace

from yoke_contracts.github_auth_transience import (
    GITHUB_AUTH_READ_ATTEMPTS,
    GITHUB_AUTH_READ_BACKOFF_SECONDS,
)
from yoke_core.domain.merge_preflight_github_lock_retry import (
    MACHINE_OPERATION_BUSY_CODE,
    call_with_machine_lock_retry,
    is_machine_operation_busy_response,
)
from yoke_core.domain.merge_queue_admission_shape import (
    candidate_shape,
    train_context,
)


def _busy() -> SimpleNamespace:
    return SimpleNamespace(
        success=False,
        error=SimpleNamespace(
            code=MACHINE_OPERATION_BUSY_CODE,
            message=(
                "another local Yoke GitHub operation is holding the "
                "machine operation lock"
            ),
        ),
    )


def _ok(result: dict) -> SimpleNamespace:
    return SimpleNamespace(success=True, result=result, error=None)


def test_busy_classifier_ignores_non_transient_auth_errors() -> None:
    response = SimpleNamespace(
        success=False,
        error=SimpleNamespace(code="github_unauthorized", message="bad credentials"),
    )
    assert is_machine_operation_busy_response(response) is False


def test_retry_replays_busy_then_returns_success() -> None:
    calls = {"n": 0}

    def call() -> SimpleNamespace:
        calls["n"] += 1
        if calls["n"] < 2:
            return _busy()
        return _ok({"claims": []})

    slept: list[float] = []
    result = call_with_machine_lock_retry(call, sleep=slept.append)
    assert result.success is True
    assert calls["n"] == 2
    assert slept == [GITHUB_AUTH_READ_BACKOFF_SECONDS[0]]


def test_retry_does_not_replay_non_transient_failure() -> None:
    calls = {"n": 0}

    def call() -> SimpleNamespace:
        calls["n"] += 1
        return SimpleNamespace(
            success=False,
            error=SimpleNamespace(code="github_unauthorized", message="bad credentials"),
        )

    slept: list[float] = []
    result = call_with_machine_lock_retry(call, sleep=slept.append)
    assert result.success is False
    assert calls["n"] == 1
    assert slept == []


def test_retry_gives_up_after_the_shared_attempt_bound() -> None:
    calls = {"n": 0}

    def call() -> SimpleNamespace:
        calls["n"] += 1
        return _busy()

    slept: list[float] = []
    result = call_with_machine_lock_retry(call, sleep=slept.append)
    assert result.success is False
    assert calls["n"] == GITHUB_AUTH_READ_ATTEMPTS
    assert slept == list(GITHUB_AUTH_READ_BACKOFF_SECONDS)


def test_candidate_shape_retries_busy_claims_list(monkeypatch) -> None:
    from yoke_core.domain import merge_preflight_github_lock_retry as retry_mod

    monkeypatch.setattr(retry_mod.time, "sleep", lambda _seconds: None)
    seen = {"claims": 0}

    def dispatch(*, function_id, target, payload):
        if function_id == "claims.path.list":
            seen["claims"] += 1
            if seen["claims"] < 2:
                return _busy()
            return _ok({"claims": []})
        return _ok({"fields": {"db_mutation_profile": ""}})

    shape, err = candidate_shape(dispatch, "YOK-200")
    assert err is None
    assert shape is not None
    assert seen["claims"] == 2


def test_train_context_retries_busy_dependency_list(monkeypatch) -> None:
    from yoke_core.domain import merge_preflight_github_lock_retry as retry_mod

    monkeypatch.setattr(retry_mod.time, "sleep", lambda _seconds: None)
    seen = {"deps": 0}

    def dispatch(*, function_id, target, payload):
        if function_id == "items.dependency.list":
            seen["deps"] += 1
            if seen["deps"] < 2:
                return _busy()
            return _ok({"dependencies": []})
        if function_id == "claims.path.list":
            return _ok({"claims": []})
        return _ok({"fields": {"db_mutation_profile": ""}})

    context, err = train_context(dispatch, "YOK-200", ())
    assert err is None
    assert context is not None
    assert seen["deps"] == 2


def test_item_resolve_retries_busy(monkeypatch) -> None:
    from yoke_core.domain import merge_preflight_github_lock_retry as retry_mod
    from yoke_core.domain import standalone_item_merge_cli as merge_cli

    monkeypatch.setattr(retry_mod.time, "sleep", lambda _seconds: None)
    calls = {"n": 0}

    def fake_dispatch(**_kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return _busy()
        return _ok({"item": {"id": 1, "public_ref": "YOK-1"}})

    monkeypatch.setattr(merge_cli, "call_dispatcher", fake_dispatch)
    item, error = merge_cli._resolve_item("YOK-1", None)
    assert error == ""
    assert item["id"] == 1
    assert calls["n"] == 2
