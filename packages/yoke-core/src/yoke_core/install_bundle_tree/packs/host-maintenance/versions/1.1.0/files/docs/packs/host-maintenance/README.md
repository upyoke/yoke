# Host Maintenance Pack

Provides bounded Docker image cleanup and recurring maintenance convergence for
a project-operated host. The two utilities are independent of any particular
application scaffold, deployment workflow, or host-provisioning method.

## Project-specific work

- Set the retention policy, schedule, disk thresholds, and service account.
- Confirm that project rollback images are retained for the intended window.
- Choose cron, systemd, or another scheduler supported by the target host.
- Wire the utilities into the project's own deploy directory and workflow.
- Verify logs, permissions, idempotence, and a safe dry run before enabling it.
