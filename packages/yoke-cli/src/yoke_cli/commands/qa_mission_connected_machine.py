"""Client adapter for ``yoke qa mission connected-machine``."""

from __future__ import annotations

from typing import List

from yoke_cli.commands._helpers import show_delegate_help

QA_MISSION_CONNECTED_MACHINE_USAGE = (
    "yoke qa mission connected-machine "
    "[--item PREFIX-N | --project P] "
    "--execution-id ID --requirement-id N --run-id N "
    "[--test-machine TEST_MACHINE] [--session-id S]"
)


def qa_mission_connected_machine(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_MISSION_CONNECTED_MACHINE_USAGE,
        "Requires the named immutable QA case or execution; item cases require "
        "the item work claim. Run it right after a connect step on the Test "
        "Machine succeeds: it records the Yoke Machine that connect registered "
        "and prints its machine_id, which a session launch's --machine takes. "
        "A Test Machine is reached only through its lease and is never a "
        "launch target; walk-end retires the recorded Machine. Pass "
        "--test-machine for a connect on a declared companion host.",
    ):
        return 0
    from yoke_cli.commands.qa_case import _run_execution_module

    return _run_execution_module(
        "yoke_core.domain.agent_mission_connected_machine_cli", args
    )


TOOL_SHAPED_SUBCOMMANDS = {
    ("qa", "mission", "connected-machine"): qa_mission_connected_machine,
}
TOOL_SHAPED_USAGE = {
    "yoke qa mission connected-machine": QA_MISSION_CONNECTED_MACHINE_USAGE,
}

__all__ = [
    "QA_MISSION_CONNECTED_MACHINE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "qa_mission_connected_machine",
]
