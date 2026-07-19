# Recovery Runbook: Yoke

What to do when Yoke's runtime or data plane needs recovery, for
humans and agents. Keep Stage and Production recovery strictly separate.

## State surfaces

- The hosted control plane uses environment-scoped PostgreSQL databases owned
  and operated by Platform. Production data is durable; Stage is disposable
  and is never a Production backup.
- Platform owns the environment Pulumi state, server custody, database backup
  policy, and deployed Yoke wheel/image pins. Its project runbook is the
  infrastructure recovery authority.
- Governed Yoke migrations rehearse against a restored validation database,
  create a verified rollback backup before live mutation, and record their
  evidence in `migration_audit`.
- Git, immutable annotated tags, GitHub Releases, the Yoke package index, and
  signed GHCR digests preserve the source and artifacts needed to reproduce a
  release.
- Local `~/.yoke` configuration and token files connect a client to Yoke; they
  are not backups of hosted application data.

## Restore procedure

1. Stop new releases and writes for the affected environment; do not disturb
   the healthy environment.
2. Record the failed deployment run, exact release tag, wheel version, image
   digest, and last known-good identities without copying secret material.
3. Use Platform's recovery runbook to restore the affected infrastructure and,
   when required, the environment database from a verified provider snapshot,
   point-in-time recovery, or governed migration backup.
4. Redeploy the last known-good Yoke wheel and server-image identities through
   the same target flow. Never edit the environment pin or container by hand as
   the completed recovery path.
5. Require schema convergence, `yoke status`, the hosted organization UI, the
   package index, and the deployment-run receipt before reopening writes.

Stage may be rebuilt instead of restored. A Production data rollback must
account for writes accepted after the recovery point; never discard them
implicitly.

## Break-glass access

Use Platform's capability-owned AWS authority and attended Systems Manager
access when the app or SSH path is unavailable. Use `prod-db-admin` only for a
sanctioned database-admin operation or audited break-glass recovery; it is not
an everyday application environment.

Never export capability secrets into the ambient shell, print a DSN or token,
copy Stage state into Production, or bypass the governed migration/restore
checks. Record the external recovery action and reconcile Platform's Pulumi and
deployment state before resuming the release train.
