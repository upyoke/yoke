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
    def test_long_begin_refusal_releases_execution_and_keeps_full_error(self) -> None:
        from yoke_core.domain.handlers.qa_plan_execution_models import (
            PlanExecutionAbortRequest,
        )
        from yoke_core.domain.qa_plan_execution import QaPlanExecutionError
        from yoke_core.domain.qa_plan_execution_begin_validation import (
            release_unusable_execution,
        )

        diagnostic = (
            "deployment_target_drifted: expected "
            + "a" * 40
            + "; live "
            + "b" * 40
            + "; inspect the frozen release. " * 20
        )
        requests = []

        def abort(**kwargs):
            assert kwargs["function_id"] == "qa.plan_execution.abort"
            requests.append(PlanExecutionAbortRequest(**kwargs["payload"]))
            return {"state": "aborted"}

        refusal = release_unusable_execution(
            abort,
            target=None,
            execution_id="begun-execution",
            subject_flag="--deployment-run-id run-example",
            actor=None,
            error=QaPlanExecutionError(diagnostic),
        )
        assert len(requests) == 1
        assert len(requests[0].reason) == 200
        assert abort_reason_code(requests[0].reason) == UNUSABLE_BEGIN_REASON
        assert "deployment_target_drifted" in requests[0].reason
        assert diagnostic.strip() in str(refusal)
        assert "has been released" in str(refusal)
        assert "correct the plan or the arguments and re-run" in str(refusal)

    def test_long_case_error_can_be_recorded_without_losing_its_code(self) -> None:
        from yoke_core.domain.handlers.qa_plan_execution import (
            PlanExecutionAbortRequest,
        )
        from yoke_core.domain.qa_plan_execution_abort_reason import (
            ABORT_REASON_MAX_LENGTH,
        )

        error = RuntimeError("SSH unavailable: " + "diagnostic detail " * 100)
        reason = continuation_abort_reason({}, error)
        recorded = PlanExecutionAbortRequest(execution_id="execution", reason=reason)
        assert len(recorded.reason) == ABORT_REASON_MAX_LENGTH
        assert abort_reason_code(recorded.reason) == CASE_EXECUTION_ERROR_REASON
        assert "SSH unavailable" in recorded.reason

    def test_case_execution_error_keeps_what_failed(self) -> None:
        reason = continuation_abort_reason({}, RuntimeError("relay unavailable"))
        assert reason.startswith(CASE_EXECUTION_ERROR_REASON)
        assert "relay unavailable" in reason

    def test_pre_host_continuation_keeps_its_own_code(self) -> None:
        reason = continuation_abort_reason(
            {"continues_execution_id": "prior"},
            _PreHostError("no lease"),
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
