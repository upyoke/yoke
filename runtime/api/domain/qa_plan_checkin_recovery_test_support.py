# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from unittest import mock

import pytest

from runtime.api.domain.qa_plan_execution_fail_closed_test_support import (
    ACTOR,
    TEST_ITEM_REF,
    _begin_result,
)

from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases,
)

from runtime.api.fixtures.pg_testdb import test_database

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

from yoke_core.domain import qa_plan_execution, qa_composed_dispatch

from yoke_core.domain.qa_plan_execution_checkin import QaPlanCommunicationUnknown

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_heartbeat

from yoke_core.domain.handlers.qa_plan_execution_reentry import handle_execution_reentry

from yoke_core.domain.qa_plan_execution_dispatch import call_plan_function


def _response(kwargs, *, result=None, code=None):
    return FunctionCallResponse(
        version="v1",
        function=kwargs["function_id"],
        request_id=kwargs["request_id"],
        success=code is None,
        result=result or {},
        error=FunctionError(code=code, message="response deadline elapsed")
        if code
        else None,
    )
