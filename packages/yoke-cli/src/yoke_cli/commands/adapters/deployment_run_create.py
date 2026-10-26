"""Flag adapter for creating a deployment run.

Split from the deployment adapter module so the run-create path — which
resolves a commit lineage from the caller's checkout and runs the version-pin
regression check against it — stays readable on its own.
"""

from __future__ import annotations

import argparse
import shlex
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
from yoke_cli.commands.adapters.deployment_run_create_retry import (
    build_timeout_repeat,
)
from yoke_cli.commands.adapters.deployment_execution_authority import (
    _same_universe_admin_env,
    creation_connection_error,
    execution_connection_error,
)
from yoke_cli.commands.adapters.deployment_pin_guard import (
    pin_regression_error,
)
from yoke_cli.commands.deployment_lineage import (
    DeploymentLineageResolutionError,
    resolve_commit_lineage,
)
from yoke_cli.transport.response_limits import (
    DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.deployment_itemless_teaching import (
    CREATE_DESCRIPTION,
    execute_created_run_note,
    replayed_run_note,
    takeover_note,
)


def _execute_connection(run_id: str) -> str:
    """The connection that will drive *run_id* at execute time.

    A run lives on the control plane that created it, so the connection this
    creation is dispatching through already determines the one `execute` must
    be given. A self-deploy replaces that control plane's API, so it is driven
    through the paired same-universe ``*-db-admin`` connection instead. Leaving it as a placeholder for the operator to fill in is what
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
    if execution_connection_error(run_id):
        return _same_universe_admin_env(active) or active
    return active


DEPLOYMENT_RUNS_CREATE_USAGE = (
    "yoke deployment-runs create PROJECT FLOW --idempotency-key KEY "
    "[--environment ENV] "
    "[--project-repo-path PATH --source-ref REF | --retry-of RUN-ID] "
    "[--artifact-json JSON | --artifact-file PATH] "
    "[--created-by WHO] [--allow-pin-regression] [--session-id S] [--json]"
)


def deployment_runs_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs create",
        usage=DEPLOYMENT_RUNS_CREATE_USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=CREATE_DESCRIPTION,
        epilog="Environment release recipe: yoke deployment-runs resolve-target --help",
    )
    parser.add_argument("project", metavar="PROJECT", help="Project to deploy.")
    parser.add_argument("flow", metavar="FLOW", help="Deployment flow to run.")
    parser.add_argument(
        "--idempotency-key",
        required=True,
        metavar="KEY",
        help=(
            "Name for the one run you mean to create. Sending the same "
            "request with the same key again returns that run instead of "
            "creating another; a new deployment needs a new key."
        ),
    )
    parser.add_argument(
        "--environment",
        dest="environment",
        default=None,
        metavar="ENV",
        help="Registered environment to deploy to; default: the flow's environment.",
    )
    parser.add_argument(
        "--created-by",
        dest="created_by",
        default="operator",
        metavar="WHO",
        help="Who created the run; default: operator.",
    )
    parser.add_argument(
        "--project-repo-path",
        default=None,
        metavar="PATH",
        help="Top folder of a git checkout of the project; needs --source-ref.",
    )
    parser.add_argument(
        "--source-ref",
        default=None,
        metavar="REF",
        help=(
            "Commit, branch or tag to release, looked up in "
            "--project-repo-path. Omit both on a flow that waits for CI to "
            "release the gate branch tip; if the tip has no CI run, its CI "
            "workflow is started. Failed or cancelled CI on the tip refuses: "
            "fix the branch or name a commit whose CI passed."
        ),
    )
    parser.add_argument(
        "--retry-of",
        default=None,
        metavar="RUN-ID",
        help="Release the same commits as this failed or cancelled run.",
    )
    artifact_group = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        artifact_group,
        "--artifact-json",
        "--artifact-file",
        dest="artifact_identity",
        help_text="Identity of the build artifact to deploy, as JSON.",
        file_help="Read the artifact identity JSON from a file.",
    )
    parser.add_argument(
        "--allow-pin-regression",
        action="store_true",
        help=(
            "Deploy even when the source pins an older version than the "
            "target environment runs now."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_CREATE_USAGE)
    if parsed is None:
        return 2
    if parsed.retry_of and parsed.project_repo_path:
        return usage_error("--retry-of cannot be combined with --project-repo-path")
    if parsed.retry_of and parsed.source_ref is not None:
        return usage_error("--retry-of cannot be combined with --source-ref")
    if (parsed.project_repo_path is None) != (parsed.source_ref is None):
        return usage_error(
            "--project-repo-path and --source-ref must be given together: the "
            "checkout resolves the named commit. Omit both to bind the "
            "gate branch tip."
        )
    if parsed.retry_of and (
        parsed.artifact_identity is not None
        or parsed.artifact_identity_file is not None
    ):
        return usage_error("--retry-of cannot be combined with artifact identity")

    def _human_writer(response, stdout, stderr) -> None:
        run_id_receipt(response, stdout, stderr)
        result = response.result or {}
        run_id = result.get("run_id")
        if run_id and result.get("replayed"):
            print(replayed_run_note(run_id, parsed.idempotency_key), file=stderr)
        if run_id and result.get("supersedes_run_id"):
            print(takeover_note(run_id, result["supersedes_run_id"]), file=stderr)
        if run_id:
            authority = _execute_connection(run_id) or "<control-plane-env>"
            print(execute_created_run_note(authority, run_id), file=stderr)

    payload = {
        "project": parsed.project,
        "flow": parsed.flow,
        "created_by": parsed.created_by,
        "idempotency_key": parsed.idempotency_key,
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
    if refusal := creation_connection_error(
        f"create {shlex.join(args)}",
        project=parsed.project,
        flow=parsed.flow,
        environment=parsed.environment,
    ):
        print(f"error: {refusal}", file=sys.stderr)
        return 2
    target = TargetRef(kind="global")
    return dispatch_and_emit(
        function_id="deployment_runs.create",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
        timeout_s=DEPLOYMENT_RUN_CREATE_TIMEOUT_SECONDS,
        response_recovery=build_timeout_repeat(target, payload),
    )


__all__ = ["deployment_runs_create", "DEPLOYMENT_RUNS_CREATE_USAGE"]
