"""CLI teaching for the supported itemless environment-release path.

Operators discover the path through ``--help`` on resolve-target-env,
create, the deployment-runs group, and watch deploy. Keep wording
project-generic. ``target_env`` is the deploy destination; the
``--env …-db-admin`` connection at execute time is the control plane
that owns the run row — verify the resolved destination rather than
assuming the two names match.
"""

from __future__ import annotations

# Copy-pasteable recipe shown on the surfaces that own each step.
ITEMLESS_RELEASE_RECIPE = """\
Itemless environment release (project-generic):
  TARGET_ENV=$(yoke deployment-runs resolve-target-env PROJECT FLOW)
  # Verify TARGET_ENV is the deploy destination — do not assume it matches
  # the control-plane connection name used at create/execute time.
  # Create and execute both use the owner-only local-postgres connection so
  # run rows stay writable when the HTTPS product plane is the deploy target.
  RUN_ID=$(yoke --env CONTROL-PLANE-db-admin deployment-runs create PROJECT FLOW \\
    --target-env "$TARGET_ENV" \\
    --project-repo-path /path/to/checkout \\
    --source-ref origin/main)
  yoke --env CONTROL-PLANE-db-admin watch deploy -- "$RUN_ID"

Retry a failed or cancelled run without following a moving branch:
  RETRY_ID=$(yoke --env CONTROL-PLANE-db-admin deployment-runs create \
    PROJECT FLOW --target-env "$TARGET_ENV" --retry-of FAILED_RUN_ID)
  yoke --env CONTROL-PLANE-db-admin watch deploy -- "$RETRY_ID"
"""

RESOLVE_TARGET_ENV_DESCRIPTION = (
    "Resolve the flow's target environment (or honor --target-env). "
    "Prints the destination env id for create --target-env. Always verify "
    "the printed value: it is the environment being deployed TO, not the "
    "control-plane connection name used later for watch deploy / execute."
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
    "watcher. For an itemless environment release, resolve the target "
    "env, create the run with --project-repo-path and --source-ref, then "
    "drive it here through the control-plane db-admin connection. Verify "
    "the resolved target_env rather than assuming it matches the --env "
    "connection name."
)


def execute_created_run_note(authority: str, run_id: str) -> str:
    """Post-create stderr line pointing at the watch-deploy execute path."""
    return (
        f"note: run stays 'created' until executed: yoke --env "
        f"{authority} watch deploy -- {run_id}"
    )


__all__ = [
    "CREATE_DESCRIPTION",
    "ITEMLESS_RELEASE_RECIPE",
    "RESOLVE_TARGET_ENV_DESCRIPTION",
    "WATCH_DEPLOY_DESCRIPTION",
    "execute_created_run_note",
]
