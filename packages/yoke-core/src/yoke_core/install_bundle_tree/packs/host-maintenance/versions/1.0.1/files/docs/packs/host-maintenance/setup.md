# Host Maintenance Pack Setup

This Pack installs project-scoped Docker image cleanup, recurring safe
maintenance convergence, and a setup helper. It depends on container-runtime.

## Install

    yoke packs get host-maintenance /path/to/project --project <project>
    yoke packs get host-maintenance /path/to/project --project <project> --apply

Review ops/docker_image_cleanup.py,
ops/docker_maintenance_converge.py, and
ops/setup-vps-maintenance.sh in the target project before running them.

On later updates, review the returned patch like any other project change.
Customized files stay customized, and a project-deleted file stays deleted
unless the newer Pack also changes that same file and reports a conflict.

## Apply to a host

Copy only the reviewed project-owned files to the intended host using the
project's normal SSH authority. Run the convergence helper first without
privilege, verify its installed job and paths, then use the documented
remove-only privileged mode only when retiring a conflicting root-owned job.

The deployment workflow may stream docker_image_cleanup.py over SSH after a
healthy deployment. The helper limits cleanup to the project's repository and
explicit keep image; it never performs a global all-images prune.

## Verify

- Confirm the expected user owns the scheduled job.
- Confirm only project-scoped or dangling Docker material is eligible.
- Confirm active containers and explicitly kept images survive.
- Re-run convergence and require an idempotent result.
- Exercise a transient Docker failure and confirm retries remain visible.

## Intentional project-specific gaps

The project must decide host sharing, disk thresholds, maintenance windows,
alerting, backup, log retention, privilege boundaries, and emergency recovery.
If multiple projects share a host, their cleanup policies must be reconciled in
that host's project-owned runbook before enabling automation.
