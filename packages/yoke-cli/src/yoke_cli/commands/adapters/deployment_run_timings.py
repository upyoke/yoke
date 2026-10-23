"""CLI adapter for a deployment run's recorded release phase timings."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


DEPLOYMENT_RUNS_TIMINGS_USAGE = (
    "yoke deployment-runs timings RUN-ID [--full] [--session-id S] [--json]"
)


def deployment_runs_timings(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs timings",
        usage=DEPLOYMENT_RUNS_TIMINGS_USAGE,
        description=(
            "Show how long each release step of a deployment run took: the\n"
            "elapsed time per step, then every start and end record. --json\n"
            "prints the records in full."
        ),
    )
    parser.add_argument(
        "run_id", metavar="RUN-ID", help="Deployment run id, such as run-YYYYMMDD-NNN."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_TIMINGS_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        stdout.write(f"run: {result.get('run_id')} ({result.get('status')})\n")
        if result.get("note"):
            stdout.write(f"note: {result['note']}\n")
            return
        stdout.write("steps (elapsed ms, ended count, outcomes):\n")
        for step in result.get("steps") or []:
            outcomes = ",".join(str(o) for o in step.get("outcomes") or [])
            stdout.write(
                f"  {step['step']}: {step['elapsed_ms']} ({step['count']}, {outcomes})\n"
            )
        stdout.write("records (timestamp phase step elapsed_ms outcome):\n")
        for record in result.get("records") or []:
            elapsed = record.get("elapsed_ms")
            stdout.write(
                f"  {record.get('timestamp')} {record.get('phase')} {record.get('step')}"
                + (f" {elapsed} {record.get('outcome')}" if elapsed is not None else "")
                + "\n"
            )

    return dispatch_and_emit(
        function_id="deployment_runs.timings",
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["DEPLOYMENT_RUNS_TIMINGS_USAGE", "deployment_runs_timings"]
