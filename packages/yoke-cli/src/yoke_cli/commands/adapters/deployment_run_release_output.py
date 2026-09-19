"""Flag adapter for recording a commit a release's own automation produced."""

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


DEPLOYMENT_RUNS_RELEASE_OUTPUT_RECORD_USAGE = (
    "yoke deployment-runs release-output record RUN-ID --project P "
    "[--commit REF] [--reason R] [--session-id S] [--json]"
)

_DESCRIPTION = """\
Record a commit this deployment run's own automation wrote.

A promotion that rewrites a version pin pushes a real commit no backlog item
authored, and the next release's composition validation finds nothing to
attribute it to. Recording it here attributes it to the run that produced it,
so that release validates without a hand-written composition_resolution while
genuinely unattributed code still refuses.

Omit --commit and the branch this run's own flow bound for that project is
resolved instead, so no caller has to name a repository branch the control
plane already recorded.

Four claims are checked before anything is written: the run has started, the
ref resolves in the project's source, the commit is not the one the run
pinned and does descend from it, and no backlog item already owns it. That
last one matters most — such a commit is the item's work however it is
labelled here, and recording it would waive the delivery proof the item owes.
Every refusal names itself and the repair.
"""


def deployment_runs_release_output_record(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs release-output record",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_DESCRIPTION,
    )
    parser.add_argument("run_id")
    parser.add_argument(
        "--project",
        required=True,
        help="Project whose source holds the produced commit.",
    )
    parser.add_argument(
        "--commit",
        default="",
        help=(
            "The commit the run's automation produced, as any ref the "
            "project's source resolves. Omit it to resolve the branch this "
            "run's own flow bound for that project."
        ),
    )
    parser.add_argument(
        "--reason",
        default="release_pin_materialization",
        help="What the automation wrote it for.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_RUNS_RELEASE_OUTPUT_RECORD_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        run = result.get("run_id")
        project = result.get("project")
        if result.get("outcome") == "no_commit_produced":
            print(
                f"{run} added no commit to {project}; its bound branch still "
                "points at the source it pinned, so there is no release "
                "output to record",
                file=stdout,
            )
            return None
        verb = "recorded" if result.get("recorded") else "already recorded"
        print(
            f"{run} {verb} {str(result.get('commit_sha'))[:12]} in {project} "
            f"as release output ({result.get('reason')})",
            file=stdout,
        )
        return None

    return dispatch_and_emit(
        function_id="deployment_runs.release_output.record",
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={
            "project": parsed.project,
            "commit_sha": parsed.commit,
            "reason": parsed.reason,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "deployment_runs_release_output_record",
    "DEPLOYMENT_RUNS_RELEASE_OUTPUT_RECORD_USAGE",
]
