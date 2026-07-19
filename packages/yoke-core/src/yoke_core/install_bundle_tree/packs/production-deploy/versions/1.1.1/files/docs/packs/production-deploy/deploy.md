# Production Deploy Pack Runbook

This is generic guidance for the VPS, Docker Compose, and CloudFront workflow
installed by production-deploy. Replace it with exact project-owned commands,
contacts, and recovery decisions before production use.

## Delivery shape

The normal and hotfix workflows:

1. Check out the exact dispatched commit.
2. Use GitHub OIDC to assume the repository's IaC-owned delivery role.
3. Establish SSH trust using project-specific host secrets.
4. Converge safe Docker host maintenance.
5. Choose an incremental rebuild only when current production is healthy;
   otherwise use the cold-start rebuild path.
6. rsync application and Compose source to the target host.
7. Rebuild and start the Compose project.
8. Gate on API, web, and configured smoke paths.
9. Reclaim only safe superseded Docker material.
10. Remove stale preview environments without touching active branches.
11. Require CloudFront invalidation to succeed.

Hotfix is manual-dispatch only and requires the Yoke correlation input. Normal
delivery uses the project's configured Yoke flow; neither workflow should be
hand-dispatched as the ordinary item-delivery path.

## Before a run

1. Confirm the intended branch and full commit SHA.
2. Confirm CI and project-specific verification for that SHA.
3. Confirm the active flow targets the intended environment.
4. Confirm YOKE_DELIVERY_CI_ROLE_ARN and the production environment protection.
5. Confirm the host, deploy user, backup state, free disk, and current service
   health.
6. Review any customized workflow or Compose changes.

## Start and observe

Use the project's configured deployment flow or its normal item-bound Yoke
delivery command. Record:

- Yoke deployment run id;
- GitHub workflow run id and URL;
- exact source SHA;
- target environment;
- assumed role identity;
- API, web, and smoke results;
- CloudFront invalidation id; and
- final deployed version marker.

Do not treat workflow dispatch as completion. Completion requires the service
and public URL to report the expected SHA and health.

## Failure handling

### Build fails before replacement

The running service should remain untouched on the incremental path. Capture
the failing build logs, fix the project source, and dispatch a new immutable
commit.

### Replacement or health check fails

Stop automation, preserve logs and the prior image/source identity, and follow
the project's rollback runbook. This Pack cannot know whether rollback means a
prior image, prior commit, database-compatible release, or full restore.

### OIDC assumption fails

Check the repository, environment subject, role variable, issuer, audience, and
trust policy. Do not add static AWS keys as a fallback.

### CloudFront invalidation fails

Treat the deployment as failed. Check that the configured distribution belongs
to the project and the assumed role has the minimum invalidation authority.
Rerun only after correcting the role, distribution, or AWS failure.

### SSH or host maintenance fails

Check host reachability, key rotation, deploy-user permissions, Docker daemon
health, disk pressure, and the installed host-maintenance helper. Avoid global
Docker prune commands on a shared host.

## Project-specific gaps

The project must document:

- exact backup and restore procedures;
- database migration compatibility and rollback limits;
- zero-downtime or maintenance-window requirements;
- host replacement and secret recovery;
- public health and synthetic checks;
- incident ownership and escalation;
- retention and cleanup policies; and
- the evidence required to call a run complete.

Run ops/verify-deployment.sh only if its domain, redirect, TLS, and direct-origin
assumptions match the project. Otherwise replace it with project-owned checks.
