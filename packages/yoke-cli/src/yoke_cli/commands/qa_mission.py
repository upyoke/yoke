"""Client adapters for the steps of an exploratory QA mission walk."""

from __future__ import annotations

from typing import List

from yoke_cli.commands._helpers import show_delegate_help
from yoke_cli.commands.qa_case import (
    QA_MISSION_HOST_COMMAND_MODULE,
    run_execution_module,
)

_QA_MISSION_HOST_COPY_MODULE = "yoke_core.domain.agent_mission_host_copy_cli"
_QA_MISSION_WALK_MODULE = "yoke_core.domain.agent_mission_walk_cli"

QA_MISSION_HOST_COMMAND_USAGE = (
    "yoke qa mission host-command "
    "[--item PREFIX-N | --project P] "
    "--execution-id ID --requirement-id N [--test-machine TEST_MACHINE] "
    "[--gui-session] [--timeout-seconds N] [--session-id S] -- ARGV..."
)
QA_MISSION_HOST_COPY_USAGE = (
    "yoke qa mission host-copy "
    "[--item PREFIX-N | --project P] "
    "--execution-id ID --requirement-id N [--test-machine TEST_MACHINE] "
    "--from TARGET_PATH --to LOCAL_PATH [--session-id S]"
)
QA_MISSION_WALK_START_USAGE = (
    "yoke qa mission walk-start "
    "[--item PREFIX-N | --project P] "
    "--execution-id ID --requirement-id N [--session-id S]"
)
QA_MISSION_WALK_END_USAGE = (
    "yoke qa mission walk-end "
    "[--item PREFIX-N | --project P] "
    "--execution-id ID --requirement-id N --run-id N [--timeout-seconds N] [--session-id S]"
)


def qa_mission_host_command(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_MISSION_HOST_COMMAND_USAGE,
        "Requires the named immutable QA case or execution; item cases require the item work claim.",
    ):
        return 0
    return run_execution_module(
        QA_MISSION_HOST_COMMAND_MODULE,
        args,
    )


def qa_mission_host_copy(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_MISSION_HOST_COPY_USAGE,
        "Requires the named immutable QA case or execution; item cases require the item work claim. "
        "Writes the file's exact bytes to LOCAL_PATH; then upload it with "
        "`yoke qa artifact add ... --content-file LOCAL_PATH`.",
    ):
        return 0
    return run_execution_module(_QA_MISSION_HOST_COPY_MODULE, args)


def qa_mission_walk_start(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_MISSION_WALK_START_USAGE,
        "Requires the named immutable QA case or execution; item cases require the item work claim.",
    ):
        return 0
    return run_execution_module(_QA_MISSION_WALK_MODULE, ["start", *args])


def qa_mission_walk_end(args: List[str]) -> int:
    if show_delegate_help(
        args,
        QA_MISSION_WALK_END_USAGE,
        "Requires the named immutable QA case or execution; item cases require the item work claim.",
    ):
        return 0
    return run_execution_module(_QA_MISSION_WALK_MODULE, ["end", *args])


TOOL_COMMANDS = {
    ("qa", "mission", "host-command"): qa_mission_host_command,
    ("qa", "mission", "host-copy"): qa_mission_host_copy,
    ("qa", "mission", "walk-start"): qa_mission_walk_start,
    ("qa", "mission", "walk-end"): qa_mission_walk_end,
}

USAGE = {
    "yoke qa mission host-command": QA_MISSION_HOST_COMMAND_USAGE,
    "yoke qa mission host-copy": QA_MISSION_HOST_COPY_USAGE,
    "yoke qa mission walk-start": QA_MISSION_WALK_START_USAGE,
    "yoke qa mission walk-end": QA_MISSION_WALK_END_USAGE,
}


__all__ = [
    "QA_MISSION_HOST_COMMAND_USAGE",
    "QA_MISSION_HOST_COPY_USAGE",
    "QA_MISSION_WALK_END_USAGE",
    "QA_MISSION_WALK_START_USAGE",
    "TOOL_COMMANDS",
    "USAGE",
    "qa_mission_host_command",
    "qa_mission_host_copy",
    "qa_mission_walk_end",
    "qa_mission_walk_start",
]
