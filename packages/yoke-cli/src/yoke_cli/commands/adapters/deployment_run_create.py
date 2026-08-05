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
)
from yoke_cli.commands.adapters.deployment_pin_guard import (
    pin_regression_error,
)
from yoke_cli.commands.deployment_lineage import (
    DeploymentLineageResolutionError,
    resolve_commit_lineage,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)


def _execute_authority() -> str:
    """The owner-only connection that will hold this run at execute time.

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
    base = active[: -len(DB_ADMIN_ENV_SUFFIX)] if active.endswith(
        DB_ADMIN_ENV_SUFFIX
    ) else active
    return f"{base}{DB_ADMIN_ENV_SUFFIX}" if base else ""


DEPLOYMENT_RUNS_CREATE_USAGE = (
    "yoke deployment-runs create PROJECT FLOW [--target-env ENV] "
    "[--project-repo-path PATH --source-ref REF] "
    "[--created-by WHO] [--allow-pin-regression] [--session-id S] [--json]"
)


def deployment_runs_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs create",
        description=(
            "Create a zero-member environment deployment run. Item-bound "
            "delivery uses `yoke usher` / runs start-for-item instead. "
            "Creation does not execute: the run stays 'created' until an "
            "operator drives it with `yoke --env <control-plane-env>-db-admin "
            "deployment-runs execute RUN-ID`."
        ),
    )
    parser.add_argument("project")
    parser.add_argument("flow")
    parser.add_argument("--target-env", dest="target_env", default=None)
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

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        run_id = result.get("run_id") or ""
        print(run_id, file=stdout)
        if run_id:
            authority = _execute_authority() or "<control-plane-env>-db-admin"
            print(
                f"note: run stays 'created' until executed: yoke --env "
                f"{authority} deployment-runs execute {run_id}",
                file=stderr,
            )
        return None

    payload = {
        "project": parsed.project,
        "flow": parsed.flow,
        "created_by": parsed.created_by,
    }
    if parsed.project_repo_path is not None:
        try:
            payload["release_lineage"] = resolve_commit_lineage(
                parsed.project_repo_path,
                parsed.source_ref,
            )
        except DeploymentLineageResolutionError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        guard_error = pin_regression_error(parsed)
        if guard_error is not None:
            print(f"Error: {guard_error}", file=sys.stderr)
            return 1
    if parsed.target_env is not None:
        payload["target_env"] = parsed.target_env
    return dispatch_and_emit(
        function_id="deployment_runs.create",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["deployment_runs_create", "DEPLOYMENT_RUNS_CREATE_USAGE"]
