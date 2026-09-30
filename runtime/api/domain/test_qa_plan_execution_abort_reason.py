"""A recorded abort reason must carry its diagnosis and stay classifiable.

Two audiences read one column. Routing readers match a stable code; the
person the refusal sends to inspect an execution's release evidence needs to
know what actually failed. Recording only the code sent that reader to
evidence that said nothing, so the reason now carries both -- and these tests
hold the second half of that bargain: a reason that gained a diagnosis must
not become an unrecognized reason.
"""

from __future__ import annotations

from yoke_core.domain.qa_plan_execution_abort_reason import (
    CASE_EXECUTION_ERROR_REASON,
    CONTINUATION_PRE_HOST_ERROR_REASON,
    UNUSABLE_BEGIN_REASON,
    abort_reason_code,
)
from yoke_core.domain.qa_plan_execution_continuation import (
    _failed_before_host,
    continuation_abort_reason,
)


class _PreHostError(RuntimeError):
    host_contact_possible = False


class TestReasonCarriesTheDiagnosis:
    def test_case_execution_error_keeps_what_failed(self) -> None:
        reason = continuation_abort_reason({}, RuntimeError("relay unavailable"))
        assert reason.startswith(CASE_EXECUTION_ERROR_REASON)
        assert "relay unavailable" in reason

    def test_pre_host_continuation_keeps_its_own_code(self) -> None:
        reason = continuation_abort_reason(
            {"continues_execution_id": "prior"}, _PreHostError("no lease"),
        )
        assert abort_reason_code(reason) == CONTINUATION_PRE_HOST_ERROR_REASON
        assert "no lease" in reason

    def test_multiline_diagnosis_stays_on_one_line(self) -> None:
        reason = continuation_abort_reason({}, RuntimeError("first\n  second"))
        assert "\n" not in reason
        assert "first second" in reason

    def test_a_silent_error_records_the_bare_code(self) -> None:
        assert continuation_abort_reason({}, RuntimeError("")) == (
            CASE_EXECUTION_ERROR_REASON
        )


class TestCodeStaysRecognizable:
    def test_code_survives_a_carried_diagnosis(self) -> None:
        reason = continuation_abort_reason({}, RuntimeError("boom: with a colon"))
        assert abort_reason_code(reason) == CASE_EXECUTION_ERROR_REASON

    def test_bare_code_reads_as_itself(self) -> None:
        assert abort_reason_code(UNUSABLE_BEGIN_REASON) == UNUSABLE_BEGIN_REASON

    def test_absent_reason_reads_as_empty(self) -> None:
        assert abort_reason_code(None) == ""

    def test_continuation_recognizes_a_reason_with_a_diagnosis(self) -> None:
        """The reader that decides a continuation may skip its host baseline."""
        execution = {
            "continues_execution_id": "prior-execution",
            "release_reason": continuation_abort_reason(
                {"continues_execution_id": "prior-execution"},
                _PreHostError("host never contacted"),
            ),
            "cursor_ordinal": 0,
        }
        assert _failed_before_host(_NoTables(), execution) is True


class _NoTables:
    """A connection stand-in for the branch that never reaches a table."""

    def execute(self, *_args, **_kwargs):  # pragma: no cover - not reached
        raise AssertionError("the pre-host branch answers without a query")
