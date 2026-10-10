"""CLI projection of the containment-only execution read."""

import argparse
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


CONTAINMENT_BASIS_USAGE = (
    "yoke deployment-runs execution containment-basis RUN-ID [--json]"
)


def containment_basis(args):
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs execution containment-basis",
        description="Read a fresh containment basis without recomposing membership. Refused while another session is the run's live driver; re-drive after repairing a named source refusal.",
    )
    parser.add_argument("run_id")
    add_json_arg(parser)
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args, CONTAINMENT_BASIS_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="deployment_runs.execution.containment_basis",
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
