"""A deployment-run create outlives the shared relay budget and recovers once."""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands import _helpers
from yoke_cli.commands.adapters import (
    deployment_run_create,
    deployment_run_create_retry,
)
from yoke_cli.transport import https as relay_module
from yoke_cli.transport import relay_telemetry
from yoke_cli.transport.https_relay_outcome import (
    is_response_timeout,
    record_outcome,
    transport_error_response,
)
from yoke_cli.transport.https_response_policy import RESPONSE_TIMEOUT_DETAIL
from yoke_cli.transport.relay_application_outcome import (
    RESPONSE_TIMEOUT_FAILURE_CLASS,
)
from yoke_cli.transport.response_limits import (
    DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS,
    DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

# The webapp's tenant upstream-call budget; nginx reads for 75 s.
HOSTED_PATH_CAP_SECONDS = 70.0
ARGS = ["yoke", "flow", "--idempotency-key", "key-1", "--session-id", "s", "--json"]


def _timeout() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="deployment_runs.create",
        version="v1",
        error=FunctionError(
            code="https_transport_failed", message=RESPONSE_TIMEOUT_DETAIL
        ),
    )


def _created(*, replayed: bool) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="deployment_runs.create",
        version="v1",
        result={"run_id": "run-1", "replayed": replayed},
    )


@pytest.fixture
def calls(monkeypatch):
    """Script the first dispatch, then the repeat; keep every call's kwargs."""
    scripted: dict = {"first": _timeout(), "repeat": _created(replayed=True)}
    seen: dict = {"first": [], "repeat": []}
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        _helpers,
        "build_actor",
        lambda session_id: ActorContext(actor_id="op", session_id=session_id or ""),
    )
    monkeypatch.setattr(
        _helpers,
        "call_dispatcher",
        lambda **kw: (seen["first"].append(kw), scripted["first"])[1],
    )
    monkeypatch.setattr(
        deployment_run_create_retry,
        "call_dispatcher",
        lambda **kw: (seen["repeat"].append(kw), scripted["repeat"])[1],
    )
    return scripted, seen


def test_create_waits_longer_than_the_shared_limit_but_under_the_hosted_cap(calls):
    scripted, seen = calls
    scripted["first"] = _created(replayed=False)

    assert deployment_run_create.deployment_runs_create(ARGS) == 0

    assert seen["first"][0]["timeout_s"] == DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS
    assert (
        DEFAULT_JSON_REQUEST_TIMEOUT_SECONDS
        < DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS
        < HOSTED_PATH_CAP_SECONDS
    )
    assert seen["repeat"] == []


def test_the_relay_hands_the_create_budget_to_the_transport(monkeypatch):
    budgets: list[float] = []

    def _open(_request, *, deadline, timeout_s):
        budgets.append(timeout_s)
        raise AssertionError("stop after the budget is observed")

    monkeypatch.setattr(relay_module, "_open_function_relay", _open)
    monkeypatch.setattr(relay_module, "record_outcome", lambda *_a, **_k: None)
    request = FunctionCallRequest(
        function="deployment_runs.create",
        actor=ActorContext(session_id="session"),
        target=TargetRef(kind="global"),
        payload={},
    )
    connection = relay_module.HttpsConnection(
        api_url="https://relay.example/api", token="t", env="prod"
    )
    with pytest.raises(AssertionError):
        relay_module.relay_https(
            request, connection, timeout_s=DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS
        )
    assert budgets == [DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS]


def test_a_timeout_repeats_once_with_the_same_key_and_returns_the_run(calls, capsys):
    _scripted, seen = calls

    assert deployment_run_create.deployment_runs_create(ARGS) == 0

    out = capsys.readouterr()
    emitted = json.loads(out.out)
    assert emitted["success"] is True
    assert emitted["result"] == {"run_id": "run-1", "replayed": True}
    assert emitted["warnings"][0]["code"] == "deployment_run_create_timeout_recovered"
    assert "returned that run" in emitted["warnings"][0]["detail"]
    assert deployment_run_create_retry.REPEAT_NOTE in out.err
    assert len(seen["first"]) == 1 and len(seen["repeat"]) == 1
    repeat = seen["repeat"][0]
    assert repeat["payload"] == seen["first"][0]["payload"]
    assert repeat["payload"]["idempotency_key"] == "key-1"
    assert repeat["timeout_s"] == DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS


def test_a_repeat_that_creates_the_run_says_the_first_never_committed(calls, capsys):
    scripted, _seen = calls
    scripted["repeat"] = _created(replayed=False)

    assert deployment_run_create.deployment_runs_create(ARGS) == 0

    warning = json.loads(capsys.readouterr().out)["warnings"][0]
    assert "before the server committed" in warning["detail"]


def test_a_second_timeout_is_reported_with_the_rerun_recovery(calls, capsys):
    scripted, seen = calls
    scripted["repeat"] = _timeout()

    assert deployment_run_create.deployment_runs_create(ARGS) == 1

    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "https_transport_failed"
    assert "re-run the identical command (same --idempotency-key)" in error["message"]
    assert len(seen["repeat"]) == 1


@pytest.mark.parametrize(
    "code", ["https_transport_failed", "release_source_off_lineage"]
)
def test_other_failures_are_not_repeated(calls, code):
    scripted, seen = calls
    scripted["first"] = FunctionCallResponse(
        success=False,
        function="deployment_runs.create",
        version="v1",
        error=FunctionError(code=code, message="could not reach the endpoint"),
    )

    assert deployment_run_create.deployment_runs_create(ARGS) == 1

    assert seen["repeat"] == []


def test_the_real_transport_refusal_is_recognised_as_a_response_timeout():
    request = FunctionCallRequest(
        function="deployment_runs.create",
        actor=ActorContext(session_id="session"),
        target=TargetRef(kind="global"),
        payload={},
    )
    timeout = transport_error_response(
        request, "https://relay.example/api", RESPONSE_TIMEOUT_DETAIL
    )
    unreachable = transport_error_response(
        request, "https://relay.example/api", "could not reach the relay"
    )

    assert is_response_timeout(timeout)
    assert not is_response_timeout(unreachable)


def test_a_response_timeout_is_recorded_as_an_unknown_application_outcome(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    recorded: list[dict] = []
    monkeypatch.setattr(relay_telemetry, "record", lambda **kw: recorded.append(kw))
    request = FunctionCallRequest(
        function="deployment_runs.create",
        actor=ActorContext(session_id="session"),
        target=TargetRef(kind="global"),
        payload={},
    )
    record_outcome(
        request,
        transport_error_response(
            request, "https://relay.example/api", RESPONSE_TIMEOUT_DETAIL
        ),
        env="prod",
        attempts=1,
    )
    record_outcome(
        request,
        transport_error_response(
            request, "https://relay.example/api", "could not reach the relay"
        ),
        env="prod",
        attempts=1,
    )

    assert [r["failure_class"] for r in recorded] == [
        RESPONSE_TIMEOUT_FAILURE_CLASS,
        "https_transport_failed",
    ]
