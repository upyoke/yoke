# Production Deploy Recovery Skeleton

This Pack cannot safely prescribe a universal recovery sequence. The target
project must replace this skeleton with exact resource names, backup authority,
data compatibility rules, and operator contacts before production use.

## First response

1. Stop further deployment mutation.
2. Record the failed run, workflow, environment, full SHA, last healthy SHA,
   public symptoms, and UTC time.
3. Preserve workflow, container, reverse-proxy, and infrastructure logs without
   copying secrets into tickets or tracked files.
4. Decide whether the failure is application, data, host, DNS/TLS/CDN, OIDC,
   or control-plane related.
5. Choose rollback, roll-forward, restore, or infrastructure recovery using the
   project's approved decision table.

## Application rollback

Document the exact prior artifact or commit, database compatibility window,
health gates, and public verification. Never assume a code rollback is safe
after an irreversible migration.

## Database recovery

Document:

- backup authority and retention;
- point-in-time and logical restore procedures;
- secret retrieval without logging values;
- tunnel or network access;
- rehearsal frequency and evidence; and
- who may authorize destructive restore steps.

## Host replacement

Document how the host is recreated through the selected VPS Pack and sanctioned
Pulumi stack, how persistent data is restored, how SSH host keys and secrets
rotate, and how DNS/CDN origins move. Preview infrastructure changes before
apply and require a clean refresh preview afterward.

## OIDC recovery

If delivery-role assumption fails, inspect the exact repository/environment
subject, issuer, audience, role variable, and trust policy. Restore IaC-owned
federation; never add static AWS keys as a temporary workflow fallback.

## DNS, TLS, and CDN recovery

Confirm the authoritative hosted zone, certificate state, origin, distribution,
and alias records. Make changes through the owning Pack's installed Pulumi
program and exact-stack Yoke boundary. A successful origin deploy is not
complete while the public route remains unhealthy.

## Closeout evidence

Record the recovered SHA, data checks, host checks, public health, CDN
invalidation, infrastructure preview, credential rotations, and follow-up
actions. Update the project-owned runbook with anything the incident proved
missing; do not change the central Pack merely to encode one project's facts.
