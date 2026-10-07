"""A bound stage refuses to dispatch once its frozen bound source is stale.

The control plane compares each recorded bound commit with its branch head;
these tests drive the driver's reading of that answer: a moved source fails
the stage with the new-run remedy, an unreadable head refuses by name, a
current source dispatches, and a plane that predates the check is not a
reason to stop a release that dispatched before it existed.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.domain import deploy_pipeline_bound_inputs as freshness
from yoke_core.domain.deployment_run_stale_bound_sources import (
    BOUND_SOURCES_CURRENT_FUNCTION_ID,
    stale_bound_source_reason,
)

FROZEN = "f" * 40
CURRENT = "c" * 40


def _answer(*, result: dict[str, Any] | None = None, code: str = "", message: str = ""):
    if code:
        return FunctionCallResponse(
            success=False,
            function=BOUND_SOURCES_CURRENT_FUNCTION_ID,
            version="v1",
            error=FunctionError(code=code, message=message),
        )
    return FunctionCallResponse(
        success=True,
        function=BOUND_SOURCES_CURRENT_FUNCTION_ID,
        version="v1",
        result=result or {},
    )


def _refusal(response: FunctionCallResponse) -> str:
    with mock.patch.object(freshness, "call_dispatcher", return_value=response) as call:
        refusal = freshness.stale_bound_source_refusal("run-test", "hosted-release")
    assert call.call_args.kwargs["function_id"] == BOUND_SOURCES_CURRENT_FUNCTION_ID
    assert call.call_args.kwargs["target"].workflow_run_id == "run-test"
    return refusal


def test_a_moved_bound_source_fails_the_stage_with_the_new_run_remedy() -> None:
    reason = stale_bound_source_reason(
        "run-test", project="platform", frozen_sha=FROZEN, current_sha=CURRENT
    )

    refusal = _refusal(
        _answer(result={"stale": [{"project": "platform", "reason": reason}]})
    )

    assert refusal == f"stage 'hosted-release' was not dispatched: {reason}"
    assert f"bound source platform {FROZEN} is stale (current {CURRENT})" in refusal
    assert "create a new run" in refusal


def test_a_current_bound_source_dispatches() -> None:
    assert _refusal(_answer(result={"stale": [], "unverified": ""})) == ""


def test_an_unreadable_branch_head_refuses_by_name() -> None:
    unverified = (
        f"bound source platform {FROZEN}: could not resolve branch 'main' of "
        "bound project 'platform': ... Register that project's checkout"
    )

    refusal = _refusal(_answer(result={"stale": [], "unverified": unverified}))

    assert refusal.startswith("stage 'hosted-release' was not dispatched: ")
    assert "could not confirm run run-test's bound sources are current" in refusal
    assert unverified in refusal


def test_a_refused_check_is_not_a_clear_one() -> None:
    refusal = _refusal(_answer(code="forbidden", message="no deploy lock held"))

    assert BOUND_SOURCES_CURRENT_FUNCTION_ID in refusal
    assert "no deploy lock held" in refusal
    assert "re-drive run-test" in refusal


@pytest.mark.parametrize("code", ["function_version_skew", "function_not_registered"])
def test_a_plane_that_predates_the_check_dispatches_and_says_so(
    code: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _refusal(_answer(code=code, message="unknown function")) == ""
    assert "dispatching without it" in capsys.readouterr().err
