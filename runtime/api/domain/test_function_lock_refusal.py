"""Function dispatch answers a lock a handler could not take by name.

A busy run row, a lock timeout and a cancelled statement each become a typed
refusal callers can retry on, never a ``handler_exception`` that reads as a
real failure and fails the deployment run that asked.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain.deployment_runs_lock import (
    RUN_BUSY_CODE,
    DeploymentRunBusy,
    RunRowLockHolder,
)
from yoke_core.domain.function_lock_refusal import (
    LOCK_TIMEOUT_CODE,
    RETRYABLE_LOCK_CODES,
    STATEMENT_CANCELLED_CODE,
    lock_refusal_outcome,
    name_lock_refusal,
)

_ENTRY = SimpleNamespace(function_id="deployment_runs.qa_stage.dispatch")


class _DatabaseError(Exception):
    def __init__(self, sqlstate: str, text: str) -> None:
        super().__init__(text)
        self.sqlstate = sqlstate


def _raising(exc: BaseException):
    def invoke(entry, request):
        raise exc

    return invoke


def test_a_busy_run_row_answers_run_busy_with_its_holder() -> None:
    busy = DeploymentRunBusy("run-1", RunRowLockHolder(pid=77, state="active", age_seconds=1800))

    outcome = name_lock_refusal(_ENTRY, None, _raising(busy))

    assert outcome.primary_success is False
    assert outcome.error.code == RUN_BUSY_CODE
    assert outcome.error.message.startswith(f"{RUN_BUSY_CODE}: deployment run 'run-1'")
    assert "pid 77 has held a deployment_runs lock for 1800s while active" in outcome.error.message


@pytest.mark.parametrize(
    ("sqlstate", "code"),
    [("55P03", LOCK_TIMEOUT_CODE), ("57014", STATEMENT_CANCELLED_CODE)],
)
def test_a_lock_timeout_or_cancelled_statement_is_named(sqlstate: str, code: str) -> None:
    exc = _DatabaseError(sqlstate, "canceling statement due to user request\nCONTEXT: x")

    outcome = name_lock_refusal(_ENTRY, None, _raising(exc))

    assert outcome.error.code == code
    assert outcome.error.message.startswith(f"{code}: {_ENTRY.function_id}")
    assert "canceling statement due to user request" in outcome.error.message
    assert "CONTEXT" not in outcome.error.message
    assert "retry the same command" in outcome.error.recovery_hint


def test_every_named_code_is_retryable() -> None:
    assert RETRYABLE_LOCK_CODES == {
        RUN_BUSY_CODE,
        LOCK_TIMEOUT_CODE,
        STATEMENT_CANCELLED_CODE,
    }


def test_any_other_failure_still_propagates() -> None:
    assert lock_refusal_outcome(_ENTRY, _DatabaseError("23505", "duplicate")) is None
    with pytest.raises(KeyError):
        name_lock_refusal(_ENTRY, None, _raising(KeyError("missing")))


def test_a_successful_handler_passes_through() -> None:
    assert name_lock_refusal(_ENTRY, None, lambda entry, request: "ok") == "ok"
