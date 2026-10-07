"""CLI teaching for the supported itemless environment-release path.

Operators discover the path through ``--help`` on resolve-target,
create, the deployment-runs group, and watch deploy. ``create`` is shared
with the item-bound batch path; creation composes membership from the
candidate, and start revalidates it. Keep wording project-generic. The resolved environment is the
deploy destination; the selected ``--env`` connection at execute time is the
control plane that owns the run row — verify the resolved destination rather
than assuming the two names match. Only a deployment targeting that control
plane's own serving API needs its paired local ``*-db-admin`` connection.
"""

from __future__ import annotations

FINALIZATION_PENDING_PREFIX = "deploy succeeded, finalization pending"

INTERRUPTED_RUN_RECOVERY = """\
Interrupted driver (watch/execute died; GitHub kept going): re-drive the
SAME run id. The dispatch correlation token reattaches to the workflow
already started and does not fire a second release.
  yoke --env CONTROL-PLANE watch deploy -- RUN-ID
A live driver (heartbeat within ten minutes) is not interrupted — a
second execute refuses by naming that session, pid, phase, and capture.
Re-drive the same run id only after that process is gone.
A self-deploy halt named `deploy driver source drift` also leaves the
run executing — re-drive the same run id; do not mint a second release.
If the driver exits 4 (deploy succeeded, finalization pending), stages
already finished — re-drive the same run id to land the succeeded stamp.
`deployment-runs terminalize` only records failed or cancelled. Do not
use it to close a run whose workflow succeeded — re-driving is the
recovery.
"""

CREATE_RETRY_GUIDANCE = """\
Create is safe to repeat under one --idempotency-key. A create that yielded
or went quiet is usually still running: continue that same invocation and
read its output. Only once it has really exited without printing a run id,
repeat the identical command with the SAME key — it returns the run the
first call created instead of minting another. The same key with any
changed input refuses `idempotency_key_conflict`, naming the run and the
differing fields. A deliberate second run of the same candidate takes a
NEW key. A control plane whose database has not yet converged the
key columns (a self-deploy's production half, before its own release
boots) cannot store the key; the create says so, and until the run starts
an identical repeat still returns it.
"""

# Copy-pasteable recipe shown on the surfaces that own each step.
ITEMLESS_RELEASE_RECIPE = (
    """\
Itemless environment release (project-generic):
  # tier|environment-name of the flow's registered target:
  yoke deployment-runs resolve-target PROJECT FLOW
  # Check delivery-ready items' selected completion flows before choosing
  # FLOW. A final member needs its selected flow unless this run carries
  # another project's source and can close that member.
  # Verify the environment name is the deploy destination — do not assume
  # it matches the selected control-plane connection name. Ordinary external
  # delivery is fully supported over HTTPS. If the target is this control
  # plane's own serving API, the CLI refuses and names the paired *-db-admin
  # connection required for that self-deploy. The run copies the flow's
  # registered environment; pass --environment ENV only to override it.
  # With no --source-ref, a flow that waits for CI binds the newest commit
  # on its gate branch's first-parent line that has its own branch CI run
  # (passed or running), or dispatches that CI on the branch and binds the
  # commit it tests; a commit off the previous release's lineage is refused
  # (release_source_off_lineage) naming both commits. Read
  # the bound commit with `deployment-runs get "$RUN_ID" release_lineage`
  # and give the release's paired run that same commit.
  RUN_ID=$(yoke --env CONTROL-PLANE deployment-runs create PROJECT FLOW \\
    --idempotency-key PROJECT-FLOW-1)
  # Or pin an exact commit; on a CI-gated flow it must have its own CI run,
  # or creation refuses (release_source_untested) naming the newest one:
  #   ... --project-repo-path /path/to/checkout --source-ref PINNED_SHA
  yoke --env CONTROL-PLANE deployment-runs validate-composition "$RUN_ID"
  yoke --env CONTROL-PLANE watch deploy -- "$RUN_ID"

Retry a failed or cancelled run without following a moving branch:
  RETRY_ID=$(yoke --env CONTROL-PLANE deployment-runs create \\
    PROJECT FLOW --retry-of FAILED_RUN_ID \\
    --idempotency-key retry-of-FAILED_RUN_ID-1)
  yoke --env CONTROL-PLANE watch deploy -- "$RETRY_ID"

Resume the same failed run without minting a new run or replaying completed stages:
  yoke --env CONTROL-PLANE watch deploy -- RUN-ID --from-stage STAGE
That re-enters executing on this run. `--retry-of` is a new run of the same candidate.

"""
    + CREATE_RETRY_GUIDANCE
    + "\n"
    + INTERRUPTED_RUN_RECOVERY
)

RESOLVE_TARGET_DESCRIPTION = (
    "Resolve the flow's target tier and registered environment (or honor "
    "--environment). Prints tier|environment-name. Always "
    "verify the printed environment: it is the one being deployed TO, not "
    "the control-plane connection name used later for watch deploy / "
    "execute."
)

CREATE_DESCRIPTION = (
    "Create a deployment run from a flow and candidate. Creation pins bound "
    "source commits and provisionally composes membership from the candidate. "
    "It reports all detectable blockers, including selected member flow "
    "mismatches, before committing a run ID. On a flow that waits for CI, "
    "the release commit must have its own run of the project's "
    "ci_workflow_file: without --source-ref creation binds the newest such "
    "commit on the gate branch (dispatching that workflow on the branch and "
    "binding the commit it tests when no commit has a run), and an explicit "
    "commit without one is "
    "refused (release_source_untested) naming the newest that has one. "
    "Commits made outside Yoke are carried without blocking release. An "
    "item a live or succeeded release already holds is not composed and not "
    "judged: it is reported as skipped, naming the run that holds it, "
    "because that run owes its delivery. A carried item with an open "
    "dependency on an unshipped blocker is skipped the same way, and a "
    "blocker a live or settling release holds has not shipped yet: the "
    "notice names that run, and the first release after it settles enrolls "
    "the dependent. "
    "A run on a flow with an item-scoped QA stage that carries or owes "
    "members must take delivery custody, or it is refused "
    "(item_qa_flow_without_delivery_custody), because its members could "
    "never be proven at item QA. Whether a memberless item-QA run owes a "
    "delivery is asked by validate-composition and before execution, not "
    "here, so add-item can attach to an itemless run. "
    "Choose the items' selected completion flow or deliberately reconcile "
    "their flow, then revalidate; creation never changes item flows. The same "
    "create-then-watch path serves an environment release and an item-bound "
    "batch; the run reports which items it enrolled. Uses the selected "
    "control-plane transport, including HTTPS for ordinary external "
    "delivery. Creation does not execute: the run stays 'created' until an "
    "operator drives it through the same control-plane connection with "
    "`yoke watch deploy`. A true self-deploy of that connection's serving "
    "API requires its paired local `*-db-admin` connection; the CLI "
    "identifies it when refusing HTTPS."
)

WATCH_DEPLOY_DESCRIPTION = (
    "Run a Yoke deployment pipeline under a shared raw+progress "
    "watcher. For an environment release or an item-bound batch, "
    "resolve the flow's target, create the run (a CI-gated flow binds "
    "its newest CI-tested commit unless --source-ref pins one), then "
    "drive it here through "
    "the same control-plane connection. Create checks composition; start "
    "revalidates it before stage dispatch. Verify the resolved environment rather than assuming "
    "it matches the --env connection name. Re-driving the same run "
    "recovers an interrupted driver by correlation token instead of "
    "dispatching a second release. Only serving-API self-deploys require "
    "the paired local db-admin env; that path freezes the driver at the "
    "run's release_lineage so a merge landing mid-run cannot mix source. "
    "The wrapper records the live driver on the run before that freeze, "
    "so a second execute refuses by name and a tail on the printed "
    "capture does not blame missing flags."
)


def replayed_run_note(run_id: str, key: str) -> str:
    """Post-create stderr line when the key returned an existing run."""
    return (
        f"note: idempotency key {key!r} already created {run_id}; returned "
        "that run instead of creating another"
    )


#: ``deployment_runs.create`` receipt ``idempotency_basis`` values.
BASIS_RECORDED_KEY = "recorded_key"
BASIS_UNCONVERGED_REQUEST_MATCH = "unconverged_request_match"


def unconverged_key_note(run_id: str, key: str, replayed: bool) -> str:
    """Post-create stderr line when the database cannot store the key yet."""
    found = (
        f"returned {run_id}, the one not-yet-started run with this exact request"
        if replayed
        else f"created {run_id}"
    )
    return (
        f"note: {found}. This control plane's deployment_runs has not "
        f"converged its idempotency columns, so key {key!r} is not stored; "
        "they arrive when the serving build boots the current release. Until "
        f"{run_id} starts, repeating this identical command returns it. Once "
        "it has started, a repeat creates another run — check `yoke "
        "deployment-runs list` first."
    )


def unkeyed_server_warning(run_id: str) -> str:
    """Post-create stderr line when the control plane ignored the key."""
    return (
        f"warning: created {run_id}, but the serving control plane predates "
        "idempotent create and ignored --idempotency-key, so repeating this "
        "command WILL mint another run. Before any repeat, check "
        "`yoke deployment-runs list` for a run already created; install the "
        "current Yoke release on that control plane to make create retry-safe."
    )


def execute_created_run_note(authority: str, run_id: str) -> str:
    """Post-create stderr line pointing at the watch-deploy execute path."""
    return (
        f"note: run stays 'created' until executed: yoke --env "
        f"{authority} watch deploy -- {run_id}"
    )


__all__ = [
    "BASIS_RECORDED_KEY",
    "BASIS_UNCONVERGED_REQUEST_MATCH",
    "CREATE_DESCRIPTION",
    "CREATE_RETRY_GUIDANCE",
    "FINALIZATION_PENDING_PREFIX",
    "INTERRUPTED_RUN_RECOVERY",
    "ITEMLESS_RELEASE_RECIPE",
    "RESOLVE_TARGET_DESCRIPTION",
    "WATCH_DEPLOY_DESCRIPTION",
    "execute_created_run_note",
    "replayed_run_note",
    "unconverged_key_note",
    "unkeyed_server_warning",
]
