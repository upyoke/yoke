"""CLI teaching for the supported itemless environment-release path.

Operators discover the path through ``--help`` on resolve-target,
create, the deployment-runs group, and watch deploy. Keep wording
project-generic. The resolved environment is the deploy destination; the
``--env …-db-admin`` connection at execute time is the control plane
that owns the run row — verify the resolved destination rather than
assuming the two names match.
"""

from __future__ import annotations

INTERRUPTED_RUN_RECOVERY = """\
Interrupted driver (watch/execute died; GitHub kept going): re-drive the
SAME run id. The dispatch correlation token reattaches to the workflow
already started and does not fire a second release.
  yoke --env CONTROL-PLANE-db-admin watch deploy -- RUN-ID
`deployment-runs terminalize` only records failed or cancelled. Do not
use it to close a run whose workflow succeeded — re-driving is the
recovery.
"""

# Copy-pasteable recipe shown on the surfaces that own each step.
ITEMLESS_RELEASE_RECIPE = """\
Itemless environment release (project-generic):
  # tier|environment-name of the flow's registered target:
  yoke deployment-runs resolve-target PROJECT FLOW
  # Verify the environment name is the deploy destination — do not assume
  # it matches the control-plane connection name used at create/execute
  # time. Create and execute both use the owner-only local-postgres
  # connection so run rows stay writable when the HTTPS product plane is
  # the deploy target. The run copies the flow's registered environment;
  # pass --environment ENV only to override it.
  RUN_ID=$(yoke --env CONTROL-PLANE-db-admin deployment-runs create PROJECT FLOW \\
    --project-repo-path /path/to/checkout \\
    --source-ref origin/main)
  yoke --env CONTROL-PLANE-db-admin watch deploy -- "$RUN_ID"

Retry a failed or cancelled run without following a moving branch:
  RETRY_ID=$(yoke --env CONTROL-PLANE-db-admin deployment-runs create \
    PROJECT FLOW --retry-of FAILED_RUN_ID)
  yoke --env CONTROL-PLANE-db-admin watch deploy -- "$RETRY_ID"

""" + INTERRUPTED_RUN_RECOVERY

RESOLVE_TARGET_DESCRIPTION = (
    "Resolve the flow's target tier and registered environment (or honor "
    "--environment). Prints tier|environment-name. Always "
    "verify the printed environment: it is the one being deployed TO, not "
    "the control-plane connection name used later for watch deploy / "
    "execute."
)

CREATE_DESCRIPTION = (
    "Create a zero-member environment deployment run. Item-bound "
    "delivery uses `yoke usher` / runs start-for-item instead. "
    "Requires the configured same-universe owner-only local-postgres "
    "connection, not the HTTPS product plane — run records must stay "
    "writable when that plane is the deploy target. Creation does not "
    "execute: the run stays 'created' until an operator drives it through "
    "the same owning control-plane db-admin connection with "
    "`yoke watch deploy`."
)

WATCH_DEPLOY_DESCRIPTION = (
    "Run a Yoke deployment pipeline under a shared raw+progress "
    "watcher. For an itemless environment release, resolve the flow's "
    "target, create the run with --project-repo-path and --source-ref, "
    "then drive it here through the control-plane db-admin connection. "
    "Verify the resolved environment rather than assuming it matches the "
    "--env connection name. Re-driving the same run recovers an interrupted "
    "driver by correlation token instead of dispatching a second release."
)


def execute_created_run_note(authority: str, run_id: str) -> str:
    """Post-create stderr line pointing at the watch-deploy execute path."""
    return (
        f"note: run stays 'created' until executed: yoke --env "
        f"{authority} watch deploy -- {run_id}"
    )


__all__ = [
    "CREATE_DESCRIPTION",
    "INTERRUPTED_RUN_RECOVERY",
    "ITEMLESS_RELEASE_RECIPE",
    "RESOLVE_TARGET_DESCRIPTION",
    "WATCH_DEPLOY_DESCRIPTION",
    "execute_created_run_note",
]
