# Onboard Steps 6–7: Domain And Gated Infra Apply + First Deploy

## Step 6: Domain

Entry: registered hosting or live deferred/not-needed branch. Skip only a
domain result matching that **live** branch; an old no-host answer cannot
skip newly verified/configured hosting.

### Hosting deferred/not-needed: close the hosted rows

Step 5 must have verified a registered merge-only default or an empty default;
continue directly to step 8 without managed domain/deploy. Choose the live answer:

```bash
yoke onboard checklist --run-id {run_id} --row-status domain-setup=not-needed --evidence domain-setup="hosting deferred; no managed domain" --row-status infra-apply-first-deploy=deferred --evidence infra-apply-first-deploy="hosting postponed; no managed deploy route"
yoke onboard checklist --run-id {run_id} --row-status domain-setup=not-needed --evidence domain-setup="hosting not needed; no managed domain" --row-status infra-apply-first-deploy=not-needed --evidence infra-apply-first-deploy="confirmed profile has no Yoke-managed host"
```

### Hosting verified/configured: record the domain

Default subdomain derives from slug. Bring-your-own hosted zone/certificate is
follow-on; domain registration is outside this skill. Write scalar leaves on
the actual registered environments the apply uses:

```bash
yoke projects environment-settings merge --project {project} --environment stage --set domain.mode=default-subdomain --set domain.hostname={slug}.{default_domain}
yoke projects environment-settings merge --project {project} --environment prod --set domain.mode=default-subdomain --set domain.hostname={slug}.{default_domain}
yoke projects environment-settings get --project {project} --environment stage --path domain.hostname --json
yoke projects environment-settings get --project {project} --environment prod --path domain.hostname --json
yoke onboard checklist --run-id {run_id} --row-status domain-setup=configured --evidence domain-setup="default subdomain {hostname} verified on registered environments; bring-your-own deferred"
```

Merge receipt names changed paths only. Echo projected values. Failure blocks
domain-setup with command/recovery and stops.

## Step 7: Gated Infra Apply + First Deploy

Entry: live hosting-setup=verified|configured and all prior managed steps satisfied;
the no-host branch above does not enter this gate. Skip only applied infra
plus a healthy live deployment: report URL. Old deferred/not-needed is no proof.

Present full installed-Pack resource preview: state backend, registry, hosts,
DNS, TLS/firewall, CI OIDC provider/trust-scoped roles and resulting repository
Actions variables. Use the Pack's preview entrypoint under resolver-materialized
capability credentials; no shell export, logging or chat secrets.
Then explain stage build → deploy → smoke; production keeps its later gate.

Explicit yes only: [y/N] defaults No. Otherwise record
infra-apply-first-deploy=deferred, operator declined apply, then allow step 8.

After approval, execute Pack-documented infrastructure order, project-declared
stage build/deploy flow and stage smoke. Read the delivery rules and hold the
project DEPLOY coordination claim before creating/executing a deployment run;
release it afterward. Pack entrypoints own invocation and capability resolution.
`yoke aws exec --project {project} -- {aws-args}` is an operator raw-AWS
pass-through, not a generic Pulumi/app launcher. Capture and stream long
commands, inspecting their capture on failure.

```bash
yoke onboard checklist --run-id {run_id} --row-status infra-apply-first-deploy=verified --evidence infra-apply-first-deploy="infra applied; first stage deploy {stage_url}; smoke passed"
```

Echo URL and smoke. Apply/deploy failure blocks the row, preserves completed
writes and stops; reentry re-presents the same gate and reapplies idempotently
through the state backend. Smoke failure stays up for diagnosis: no teardown
or automatic retry.

```bash
yoke onboard checklist --run-id {run_id} --row-status infra-apply-first-deploy=blocked --blocker infra-apply-first-deploy="{failed stage}: {captured error}; live URL {stage_url}; re-run /yoke onboard --run-id {run_id} to re-approve and retry"
```

Requested live-infra/app reconfigure presents its delta behind the same gate;
never silently reapply. Next: [seed-work.md](seed-work.md).
