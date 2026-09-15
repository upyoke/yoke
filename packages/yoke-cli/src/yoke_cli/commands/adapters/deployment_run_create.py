"""Flag adapter for creating a deployment run.

Split from the deployment adapter module so the run-create path — which
resolves a commit lineage from the caller's checkout and runs the version-pin
regression check against it — stays readable on its own.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    run_id_receipt,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_cli.commands.adapters.deployment_pin_guard import (
    pin_regression_error,
)
from yoke_cli.commands.deployment_lineage import (
    DeploymentLineageResolutionError,
    resolve_commit_lineage,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.deployment_itemless_teaching import (
    CREATE_DESCRIPTION,
    ITEMLESS_RELEASE_RECIPE,
    execute_created_run_note,
)


def _execute_connection() -> str:
    """The selected connection that will address this run at execute time.

    A run lives on the control plane that created it, so the connection this
    creation is dispatching through already determines the one `execute` must
    be given. Leaving it as a placeholder for the operator to fill in is what
    produces a run driven through the wrong connection, which surfaces as
    'deployment run not found' — a message that reads as a missing run rather
    than a wrong control plane.

    Empty when there is no active env to name, so the caller falls back to the
    placeholder rather than printing a confidently wrong recipe.
    """
    import os

    active = os.environ.get(ENV_OVERRIDE, "").strip()
    if not active:
        return ""
    return active


DEPLOYMENT_RUNS_CREATE_USAGE = (
    "yoke deployment-runs create PROJECT FLOW [--environment ENV] "
    "[--project-repo-path PATH --source-ref REF | --retry-of RUN-ID] "
    "[--artifact-json JSON | --artifact-file PATH] "
    "[--created-by WHO] [--allow-pin-regression] [--session-id S] [--json]"
)


def deployment_runs_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs create",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=CREATE_DESCRIPTION,
        epilog=ITEMLESS_RELEASE_RECIPE,
    )
    parser.add_argument("project")
    parser.add_argument("flow")
    parser.add_argument("--environment", dest="environment", default=None)
    parser.add_argument("--created-by", dest="created_by", default="operator")
    parser.add_argument(
        "--project-repo-path",
        default=None,
        help=(
            "Git top-level used to bind release_lineage mechanically from "
            "the selected remote source ref."
        ),
    )
    parser.add_argument(
        "--source-ref",
        default="origin/main",
        help="Commit-ish to bind when --project-repo-path is supplied.",
    )
    parser.add_argument(
        "--retry-of",
        default=None,
        help=(
            "Reuse the immutable release lineage pinned on a failed or "
            "cancelled deployment run."
        ),
    )
    artifact_group = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        artifact_group,
        "--artifact-json",
        "--artifact-file",
        dest="artifact_identity",
    )
    parser.add_argument(
        "--allow-pin-regression",
        action="store_true",
        help=(
            "Deploy even when the source ref carries an older version pin "
            "than the target environment currently runs."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_CREATE_USAGE)
    if parsed is None:
        return 2
    if parsed.retry_of and parsed.project_repo_path:
        return usage_error("--retry-of cannot be combined with --project-repo-path")
    if parsed.retry_of and "--source-ref" in args:
        return usage_error("--retry-of cannot be combined with --source-ref")
    if parsed.retry_of and (
        parsed.artifact_identity is not None
        or parsed.artifact_identity_file is not None
    ):
        return usage_error("--retry-of cannot be combined with artifact identity")
    def _human_writer(response, stdout, stderr) -> None:
        run_id_receipt(response, stdout, stderr)
        run_id = (response.result or {}).get("run_id")
        if run_id:
            authority = _execute_connection() or "<control-plane-env>"
            print(execute_created_run_note(authority, run_id), file=stderr)

    payload = {
        "project": parsed.project,
        "flow": parsed.flow,
        "created_by": parsed.created_by,
    }
    if parsed.retry_of is not None:
        payload["retry_of"] = parsed.retry_of
    if (
        parsed.artifact_identity is not None
        or parsed.artifact_identity_file is not None
    ):
        try:
            payload["artifact_identity"] = resolve_text_file(
                parsed.artifact_identity,
                parsed.artifact_identity_file,
                "--artifact-file",
            )
        except ValueError as exc:
            return usage_error(str(exc))
    if parsed.project_repo_path is not None:
        try:
            payload["release_lineage"] = resolve_commit_lineage(
                parsed.project_repo_path,
                parsed.source_ref,
            )
        except DeploymentLineageResolutionError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    if parsed.retry_of is not None or parsed.project_repo_path is not None:
        guard_error = pin_regression_error(parsed)
        if guard_error is not None:
            print(f"Error: {guard_error}", file=sys.stderr)
            return 1
    if parsed.environment is not None:
        payload["environment"] = parsed.environment
    return dispatch_and_emit(
        function_id="deployment_runs.create",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["deployment_runs_create", "DEPLOYMENT_RUNS_CREATE_USAGE"]
