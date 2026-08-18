# Onboard Steps 6–7: Domain Record And The Gated First Deploy

Step 6 records the domain posture the infra apply consumes. Step 7 is the second of the two stops: the full infrastructure apply plus first deploy, behind an explicit `[y/N]` gate that defaults No.

## Step 6: Domain

- **Entry:** environments registered.
- **Skip:** domain posture already recorded → skip.
- **Row:** `domain-setup`.

The launch posture is the default subdomain derived from the project slug; bring-your-own domain (hosted zone plus certificate) is a follow-on, and registering domains through Yoke is out of scope here. Record the choice on the environment settings the apply reads, as scalar leaves:

```bash
yoke projects environment-settings merge --project {project} \
  --environment stage --set domain.mode=default-subdomain \
  --set domain.hostname={slug}.{default_domain}
yoke projects environment-settings merge --project {project} \
  --environment prod --set domain.mode=default-subdomain \
  --set domain.hostname={slug}.{default_domain}
```

The merge receipt returns changed paths only. Verify by projecting the leaf back (`yoke projects environment-settings get --project {project} --environment stage --path domain.hostname --json`), echo it, then mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status domain-setup=configured \
  --evidence domain-setup="default subdomain recorded: {hostname} on stage+prod; bring-your-own deferred"
```

**Failure floor:** `domain-setup=blocked` with the failing merge and recovery recipe; stop.

## Step 7: Gated Infra Apply + First Deploy

- **Entry:** every earlier step satisfied.
- **Skip:** infra applied and the deploy live and healthy → report the URL and skip.
- **Row:** `infra-apply-first-deploy`.

### The gate (stop 2 of 2)

Present the full preview before anything runs:

- The infrastructure resource preview from the installed Packs' stacks (run the Pack-provided preview surface, e.g. `pulumi preview` in the Pack's infra directory, under the resolver-materialized env below) — the state backend, registry, hosts, DNS, and the CI OIDC provider plus trust-scoped CI roles whose ARNs land in repository Actions variables (CI federates per run; applies stay on the local `aws-admin` capability).
- What follows the apply: build → deploy → smoke on stage. Prod keeps its own later gate and is not part of this step.

Then take an explicit yes — `[y/N]` defaults No. Anything other than an explicit yes records the deferral and stops this step (`infra-apply-first-deploy=deferred`, evidence "operator declined the apply gate"); a deferred deploy does not block step 8.

### Credentials for the apply

Every provider-touching command runs with the `aws-admin` capability materialized into the subprocess env by the capability resolver — never exported into the shell, never printed, never in the chat:

```bash
yoke aws exec --project {project} -- {aws-args}
```

Pack-provided apply/deploy entrypoints document their own invocation; run them under the same resolver-materialized env discipline.

### Execute

1. Apply the infrastructure stacks the installed Packs provide, in their documented order.
2. Build and deploy to stage through the project's declared deploy flow surfaces.
3. Run the smoke check against the stage URL.

This is a long-running external command sequence: capture output per the command-output rules (capture file, stream progress, inspect the capture on failure).

### Evidence and marking

Success:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status infra-apply-first-deploy=verified \
  --evidence infra-apply-first-deploy="infra applied; first deploy live at {stage_url}; smoke passed"
```

Echo the deploy URL and smoke result to the operator — the first live deploy is the headline of the whole flow.

### Failure posture: re-approve and retry

- **Apply or deploy failure:** record the failure on the row (`blocked` with the failing stage and captured error), leave all completed writes in place, and stop. Re-entry re-presents the same gate and re-runs the apply — the infrastructure state backend makes the re-apply idempotent. No per-substep compensation machinery.
- **Smoke failure:** the deploy stays up for diagnosis — do not tear down, do not retry automatically. Record `blocked` with the smoke evidence and the stage URL so the operator (or the next session) can diagnose against the live environment.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status infra-apply-first-deploy=blocked \
  --blocker infra-apply-first-deploy="{failed stage}: {captured error}; deploy left up at {stage_url} for diagnosis; re-run /yoke onboard --run-id {run_id} to re-approve and retry"
```

### Reconfigure

A requested redo of live infra or the deployed app (changed domain posture, changed instance shape) re-proposes the change, shows the delta the stacks will apply, and applies it behind this same gate. Never re-apply silently.

Continue to step 8 of this skill: read [seed-work.md](seed-work.md).
