"""CLI adapter for the ``steering.backstop.*`` family."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


STEERING_BACKSTOP_EVALUATE_USAGE = (
    "yoke steering backstop evaluate --project P [--dry-run] "
    "[--executor-surface S] [--model M] [--json]"
)

STEERING_BACKSTOP_EVALUATE_DESCRIPTION = """\
Staff the steering scope's unpicked runnable work.

Runs from the live steering claim holder. It never displaces the sessions
people open themselves: it only launches a worker for work the scheduler
already calls runnable, that carries no live work claim, and that has now
waited longer than the project's grace period
(project-policy `steering_backstop_unpicked_minutes`, default 20). Launches
are capped by `steering_backstop_worker_budget` (default 2) counting the
workers this backstop already has in flight, and each staffed worker is told
to report back to the steering session by name.

Re-running is safe: each unstaffed gap carries one deterministic idempotency
key, so a second evaluation deduplicates onto the launch the first filed.

  yoke steering backstop evaluate --project yoke --dry-run
  yoke steering backstop evaluate --project yoke
"""


def _print_evaluation(response: Any, stdout, _stderr) -> None:
    result = response.result or {}
    launched = result.get("launched") or []
    withheld = result.get("withheld") or []
    print(
        f"steering backstop: project={result.get('project_id', '')} "
        f"staffed={len(launched)} withheld={len(withheld)} "
        f"in_flight={result.get('workers_in_flight', 0)}"
        f"/{result.get('worker_budget', 0)}"
        + (" (dry run)" if result.get("dry_run") else ""),
        file=stdout,
    )
    for entry in launched:
        launch = entry.get("launch") or {}
        state = "deduplicated" if entry.get("deduplicated") else launch.get("state", "")
        print(
            f"  staffed {entry.get('item_ref', '')}\t{launch.get('launch_id', '')}"
            f"\t{state}",
            file=stdout,
        )
    for entry in result.get("refused") or []:
        print(
            f"  refused {entry.get('item_ref', '')}\t{entry.get('error', '')}",
            file=stdout,
        )
    for entry in withheld:
        print(
            f"  withheld {entry.get('item_ref', '')}\t{entry.get('reason', '')}"
            f"\tunpicked {entry.get('unpicked_seconds', 0)}s",
            file=stdout,
        )


def steering_backstop_evaluate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke steering backstop evaluate",
        usage=STEERING_BACKSTOP_EVALUATE_USAGE,
        description=STEERING_BACKSTOP_EVALUATE_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be staffed without filing any launch.",
    )
    parser.add_argument(
        "--executor-surface",
        default=None,
        help="Surface to staff on; defaults to the calling session's own.",
    )
    parser.add_argument("--model", default=None, help="Model for staffed workers.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_BACKSTOP_EVALUATE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.dry_run:
        payload["dry_run"] = True
    if parsed.executor_surface:
        payload["executor_surface"] = parsed.executor_surface
    if parsed.model:
        payload["model"] = parsed.model
    return dispatch_and_emit(
        function_id="steering.backstop.evaluate",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(parsed.project),
        ),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_evaluation,
    )


USAGE_BY_FUNCTION_ID = {
    "steering.backstop.evaluate": STEERING_BACKSTOP_EVALUATE_USAGE,
}


__all__ = [
    "STEERING_BACKSTOP_EVALUATE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "steering_backstop_evaluate",
]
