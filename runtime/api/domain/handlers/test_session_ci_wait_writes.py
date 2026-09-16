"""session_ci_wait.resolve marks a received wait notified, not a second notice."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import session_ci_wait_writes as writes
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests

from runtime.api.domain.test_session_ci_wait_observer import (
    RUN_ID,
    SESSION,
    _wait_row,
    waiting_connection,  # noqa: F401 - pytest fixture reuse
)


def _request(*, session_id: str = SESSION, payload: dict | None = None):
    return FunctionCallRequest(
        function="session_ci_wait.resolve",
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload or {"run_id": RUN_ID, "conclusion": "success"},
    )


class _ConnCM:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *_exc):
        return False


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def test_resolve_is_internal_session_required() -> None:
    init_register.register_all_handlers()
    entry = lookup("session_ci_wait.resolve")
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.ambient_session_required is True
    assert entry.claim_required_kind is None
    assert entry.target_kinds == ("global",)
    assert lookup("session_ci_wait.record") is not None


def test_resolve_requires_a_session() -> None:
    outcome = writes.handle_resolve_ci_wait(_request(session_id=""))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "session_required"


def test_resolve_rejects_a_non_binding_conclusion() -> None:
    outcome = writes.handle_resolve_ci_wait(
        _request(payload={"run_id": RUN_ID, "conclusion": "timed_out"})
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"


def test_resolve_marks_the_calling_session_wait_notified(
    waiting_connection,  # noqa: F811 - pytest fixture reuse of imported name
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        writes, "_connect_rw", lambda: _ConnCM(waiting_connection)
    )

    outcome = writes.handle_resolve_ci_wait(_request())

    assert outcome.primary_success is True
    assert outcome.result_payload["resolved"] is True
    row = _wait_row(waiting_connection)
    assert row["conclusion"] == "success"
    assert row["notified_at"]
