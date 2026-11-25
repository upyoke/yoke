"""Client-readable serving floors for arguments and response fields.

These cover arguments and response fields added to functions an older
server already serves; function-id floors live in
:mod:`yoke_contracts.function_serving_floors`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


# These request forms dropped the project required by the prior server.
PROJECTLESS_TEST_MACHINE_FUNCTIONS = (
    "test_machine.bridge_diagnose",
    "test_machine.delete",
    "test_machine.desktop_access",
    "test_machine.get",
    "test_machine.golden_capture",
    "test_machine.list",
    "test_machine.operation.begin",
    "test_machine.reset", "test_machine.screenshot",
    "test_machine.settings_replace", "test_machine.verify",
)


@dataclass(frozen=True)
class ArgumentFloor:
    """The first serving version that accepts one argument of a served function.

    ``older_form`` names what to send a server below the floor instead, so the
    refusal can teach the form that server still accepts.
    """

    minimum_serving_version: str
    older_form: str


# Response fields are optional while older serving releases converge.
FUNCTION_RESPONSE_FIELD_MINIMUM_SERVING_VERSIONS = {
    "sessions.list": {"probe": "next-release", "first_user_prompt_at": "next-release"},
}


#: The ``test_machine`` argument replaced ``machine`` on these served functions;
#: ``test_machine.operation.begin`` carries the same floor beside its own.
TEST_MACHINE_ARGUMENT_FUNCTIONS = (
    "test_machine.get",
    "test_machine.settings_replace",
    "test_machine.desktop_access",
    "test_machine.verify",
    "test_machine.reset",
    "test_machine.golden_capture",
    "test_machine.bridge_diagnose",
    "test_machine.screenshot",
    "test_machine.plan_case.begin",
    "test_machine.plan_case.submit",
    "test_machine.mission.ready",
    "test_machine.mission.access",
    "qa.plan_execution.begin",
    "qa.plan_execution.resume",
)
_TEST_MACHINE_FLOOR = ArgumentFloor(
    "next-release",
    "the `machine` argument, as the `--machine NAME` flag of the Yoke CLI "
    "release that server runs",
)

#: ``--item PREFIX-N --stage S --deployment-run-id RUN`` names the item's run.
_ITEM_RUN_FLOOR = ArgumentFloor(
    "next-release",
    "`--item PREFIX-N --stage S` without --deployment-run-id, after confirming "
    "with `yoke deployment-runs get RUN` that only that run is executing S for the item",
)

#: function_id -> {argument: floor}, for arguments added to an already-served
#: function. Older request models may reject unknown arguments or silently
#: ignore them. Payload refusals name this floor; adapters whose writes can be
#: ignored must also verify the success receipt echoes the requested argument.
FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS: dict[str, dict[str, ArgumentFloor]] = {
    "sessions.list": {
        name: ArgumentFloor("next-release", "an unfiltered sessions list read; update the serving release before filtering state")
        for name in ("status",)
    },
    **{
        function_id: {
            name: ArgumentFloor(
                "next-release",
                "use the CLI release matching the server for its unpaged list",
            )
            for name in ("limit", "offset")
        }
        for function_id in ("projects.capabilities.list", "strategy.surface.list")
    },
    "ouroboros.field_note.append": {
        name: ArgumentFloor(
            "next-release", "upgrade the serving Yoke release before filing feedback"
        )
        for name in ("yoke_version", "agent")
    },
    "deployment_runs.create": {
        "flows": ArgumentFloor(
            "next-release",
            "one `yoke deployment-runs create PROJECT FLOW` per flow, each with "
            "its own --idempotency-key and the same --source-ref",
        ),
    },
    "sessions.begin": {
        "machine_scope": ArgumentFloor(
            "next-release", "start the agent inside a registered project folder"
        ),
    },
    "items.create": {
        "spec": ArgumentFloor(
            "next-release", "the filing form supported by the serving CLI release"
        ),
    },
    "items.structured_field.section_upsert": {
        "field": ArgumentFloor(
            "next-release", "field-less --section TEXT for a top-level item section"
        ),
        "heading_level": ArgumentFloor(
            "next-release", "field-less --section TEXT for a top-level item section"
        ),
    },
    "session_control.launch.create": {
        "use_stage_level": ArgumentFloor(
            "next-release",
            "an explicit --level LEVEL or exact selection with --surface S",
        ),
        "level": ArgumentFloor(
            "next-release", "an exact selection with --surface S [--model M]"
        ),
        "level_reason": ArgumentFloor(
            "next-release",
            "--level LEVEL without --level-reason, then record the reason with "
            "`yoke workflows item-posture amend PREFIX-N --key level`",
        ),
    },
    **{
        function_id: {
            "plan_execution_id": ArgumentFloor(
                "next-release",
                "a golden refreshed outside the plan: install the latest harness "
                "CLIs as the test user, then run `yoke test-machine golden-capture "
                "--project P` from the Yoke CLI release that server runs",
            ),
            **(
                {"test_machine": _TEST_MACHINE_FLOOR}
                if function_id == "test_machine.operation.begin"
                else {}
            ),
        }
        for function_id in (
            "test_machine.operation.begin",
            "test_machine.operation.submit",
            "test_machine.operation.abort",
        )
    },
    **{
        function_id: {
            "test_machine": _TEST_MACHINE_FLOOR,
            **(
                {
                    "deployment_run_id": _ITEM_RUN_FLOOR,
                    "partition": ArgumentFloor("next-release", "partition admission"),
                    "expected_sha": ArgumentFloor("next-release", "the claim holder's frozen QA lane"),
                }
                if function_id == "qa.plan_execution.begin"
                else {}
            ),
        }
        for function_id in TEST_MACHINE_ARGUMENT_FUNCTIONS
    },
    "test_machine.lease_acquire": {
        "purpose": ArgumentFloor(
            "next-release", "upgrade the serving Yoke release before retrying the idle stop"
        ),
    },
    **{
        function_id: {"deployment_run_id": _ITEM_RUN_FLOOR}
        for function_id in ("qa.plan.materialize", "qa.plan.rematerialize")
    },
    "session_control.launch.preview": {
        "level": ArgumentFloor(
            "next-release", "an exact selection with --surface S [--model M]"
        ),
        "item": ArgumentFloor(
            "next-release",
            "--level LEVEL naming the level `yoke items detail get PREFIX-N` shows",
        ),
    },
}


def declared_argument_floors(
    function_id: str, payload: Mapping[str, Any] | None
) -> dict[str, ArgumentFloor]:
    """The floors of every floored argument ``payload`` actually carries."""
    floors = FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS.get(function_id) or {}
    present = payload or {}
    return {
        name: floor
        for name, floor in floors.items()
        if present.get(name) not in (None, "", [], {})
    }


__all__ = [
    "ArgumentFloor",
    "FUNCTION_RESPONSE_FIELD_MINIMUM_SERVING_VERSIONS",
    "FUNCTION_ARGUMENT_MINIMUM_SERVING_VERSIONS",
    "PROJECTLESS_TEST_MACHINE_FUNCTIONS",
    "TEST_MACHINE_ARGUMENT_FUNCTIONS",
    "declared_argument_floors",
]
