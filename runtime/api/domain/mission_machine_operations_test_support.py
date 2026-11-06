# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import base64

import hashlib

from io import BytesIO

from PIL import Image

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)

from runtime.api.domain.machine_qa_test_support import FakeHostControl

from runtime.api.domain.agent_mission_qa_test_support import (
    ACTOR,
    _materialize_mission,
    _request,
)

from runtime.api.domain.machine_screenshot_test_support import screenshot_result

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready

from yoke_core.domain.coordination_claims import get_claim

from yoke_core.domain.handlers.machine_qa_execution_abort import handle_operation_abort

from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.host_control_runner import (
    register_host_control_factory,
    clear_host_control_factory,
)

from yoke_core.domain.machine_qa_local_execution import (
    execute_host_operation_contract,
    prepare_agent_mission_contract,
)

from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)

from yoke_core.domain.qa_plan_review import begin_plan_review


def request(payload, actor=ACTOR):
    return FunctionCallRequest(
        function="test_machine.operation",
        actor=actor,
        target=TargetRef(kind="global"),
        payload=payload,
    )


def begin(operation, actor=ACTOR):
    return handle_operation_begin(
        request(
            {
                "project": "yoke",
                "operation": operation,
                **(
                    {"destination": "/Users/Shared/yoke-golden/captured-home"}
                    if operation == "golden_capture"
                    else {}
                ),
            },
            actor,
        )
    )
