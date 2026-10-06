"""Parse and validate complete public-ref work-claim targets."""

from __future__ import annotations

import argparse

from yoke_core.domain.project_attribution import required_project
from yoke_core.domain.work_claim_targets import (
    TargetValidationError,
    WorkClaimTarget,
    make_epic_task_target,
    make_item_target,
    make_process_target,
)
from yoke_core.domain.yok_n_parser import parse_item_argument


def _parse_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", default=None, help="Item target (PREFIX-N)")
    parser.add_argument(
        "--epic-task",
        default=None,
        dest="epic_task",
        help="Epic-task parent (PREFIX-N); pair with --task-num",
    )
    parser.add_argument("--task-num", default=None, type=int, dest="task_num")
    parser.add_argument(
        "--process",
        default=None,
        help="Recurring process key (e.g. STRATEGIZE, FEED, DOCTOR)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project scope for item refs or process conflicts",
    )


def _resolve_target(parsed: argparse.Namespace) -> WorkClaimTarget:
    """Convert parsed flags into exactly one validated WorkClaimTarget.

    Refuses ambiguous or empty target specs at the CLI boundary so the
    domain layer never sees a malformed payload.
    """
    declared = [
        ("item", parsed.item),
        ("epic-task", parsed.epic_task),
        ("process", parsed.process),
    ]
    populated = [name for name, val in declared if val]
    if not populated:
        raise TargetValidationError(
            "must declare exactly one target: --item, --epic-task, or --process"
        )
    if len(populated) > 1:
        raise TargetValidationError(
            f"cannot declare multiple targets in one call: {populated}"
        )
    if parsed.item:
        return make_item_target(
            parse_item_argument(parsed.item, project=parsed.project)
        )
    if parsed.epic_task:
        if parsed.task_num is None:
            raise TargetValidationError("--epic-task requires --task-num")
        return make_epic_task_target(
            parse_item_argument(parsed.epic_task, project=parsed.project),
            parsed.task_num,
        )
    # process — make_process_target raises UnknownProcessError with known keys
    return make_process_target(
        parsed.process,
        required_project(parsed.project, operation="claiming a process"),
    )
