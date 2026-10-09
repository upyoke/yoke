# Onboard Steps 4–5: Hosting Capability And Deploy Flow

Registration/verification only; cloud writes wait for step 7 approval.

## Step 4: Hosting Capability

Read hosting_posture first. No-yoke-managed-host settles hosting-setup=not-needed,
names provider, requests no credential/probe/aws-admin. Deferred is an open
decision, never substituted for this exclusion. Empty posture asks once and
records the chosen branch:

```bash
yoke project-structure get --project {project} --family hosting_posture --json
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"hosting_posture","attachment":"project","payload":{"posture":"no-yoke-managed-host","provider":"{provider}"}}]'
```

Use posture aws-admin when Yoke manages AWS; provider is optional descriptive
prose, never execution authority.

AWS has two independent halves: connected control-plane capability settings
(region/account) and machine-local credential pair. Read both before asking.
The resolver performs an in-process caller-identity probe, redacted only;
no shell export, ambient credentials or AWS CLI required.

```bash
yoke aws admin-status --project {project} --json
```

ready true: both halves and probe passed, hosting-setup=verified, skip.
ready false/missing empty/verification.ok false: preserve pair, surface safe
reason/reset recipe, hosting-setup=blocked, stop; no ambient retry.
Missing capability_row: fill only non-secret row.
Missing machine_secrets: operator console credential creation needs explicit
approval; import **only named missing keys** through terminal stdin, never chat.
Do not re-request a saved pair.

```bash
yoke projects capability-settings merge --project {project} --cap-type aws-admin --set region={region}
yoke projects capability secret set --project {project} --cap-type aws-admin --key access_key_id --value-stdin
yoke projects capability secret set --project {project} --cap-type aws-admin --key secret_access_key --value-stdin
```

Use returned remedy only for missing halves; settings scalar --key/--value
is not registered (keys belong to secret surface). Rerun status until ready,
then configured with redacted account/identity evidence and matching posture.
Operator may explicitly defer hosting (deferred, reason, no posture write):
step 7 unreachable, step 8 still allowed. Raw yoke aws exec/preflight are
operator CLI choices, not hosting verification/VPS setup.

Remaining capabilities: GitHub app-binding selects exact accessible repository;
active only nonsuspended installation/all required permissions. Otherwise pending
binding stays disabled. Operator `yoke github connect` authorizes machine;
onboarding requests/stores/promotes no GitHub token.
Product-specific keys use capability checks and stdin import, names/redacted proof only.

```bash
yoke github status --json
yoke onboard checklist --run-id {run_id} --row-status capability-setup=configured --evidence capability-setup="GitHub mode {app-binding|disabled}; capabilities {types}; redacted verification/key names"
```

Missing operator input/access blocks the specific row with recovery and stops.

## Step 5: Infra Packs And Branch Registration

Entry: scaffold installed/mapped and live hosting answer verified/configured/
deferred/not-needed. Skip only complete **live** profile matches, including
registrations/defaults, independent QA/policy/model answers and individual receipts.
Prior `deferred` or `not-needed` values are not proof of a later hosted profile.
Read checklist each rerun; it re-evaluates the live capability probe,
registrations/default/health. Choose exactly one branch; partial managed failure
never falls through to no-host.

Confirmed infra/deploy Packs only, receipt-first then preview/apply;
no-host never gains excluded Packs. Installed source is not an infrastructure apply.

```bash
yoke packs get {pack} {checkout} --project {project}
yoke packs get {pack} {checkout} --project {project} --apply
```

The preview is also the local-tool preflight. Pulumi foundation and every
Pulumi-dependent Pack must show a `pulumi` prerequisite row with status `ready`.
Missing/unusable/outdated tool blocks with named prerequisite code and printed
OS install recipe. Stop; --allow-missing-tools only when explicitly confirmed
in the profile. Other prerequisites follow [profile-and-scaffold.md](profile-and-scaffold.md).

### Hosting verified/configured: register the site and environments

Only this branch may register managed hosting. Idempotent identical rows skip;
never overwrite an existing identity.

```bash
yoke projects site create --project {project} --site {site_name}
yoke projects environment create --project {project} --site {site_name} --environment stage
yoke projects environment create --project {project} --site {site_name} --environment prod
```

Actual non-web/non-Yoke targets need no invented stage/preview environment.
Infrastructure inventory is metadata-only; environment settings use explicit
scalar leaf projections, never whole documents.

### Persistent Deploy Flow and default

If old CI/scripts/.yoke/deployment-flows.json exist, read it as a **hint**:
none of it is contractual. Do not author/migrate/repair/delete it or depend
on parsing; other project consumers may still use it.

Validate against the serving executor **before** creation/default:

```bash
yoke deployment-flows validate --project {project} --stages-file {stages_path} --target-tier persistent --environment {environment} --status active --json
```

execution_supported=false or named schema refusal: create disabled, never assign
default/advanced preview until serving support deploys. Config-write success
is not executable proof. When supported, create each actual route:

```bash
yoke deployment-flows create {flow_id} --project {project} --name "{flow_name}" --stages-file {stages_path} --target-tier persistent --environment {environment}
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"deploy_defaults","attachment":"project","payload":{"deployment_flow":"{default_flow_id}"}}]'
yoke workflows delivery-default set --project {project} --workflow dash --flow {default_flow_id}
yoke workflows delivery-default set --project {project} --workflow issue --flow {default_flow_id}
yoke workflows delivery-default set --project {project} --workflow epic --flow {default_flow_id}
yoke workflows delivery-default set --project {project} --workflow blitz --flow {default_flow_id}
yoke project-structure deploy-defaults get --project {project}
yoke workflows mechanics get --json
```

Task exempt: never --apply-to-all. Rerun verifies all four workflow defaults,
which override project default; skip writes only when all match. Do not change
another project/item's shared definition. Persistent binds exactly one registered
environment; ephemeral binds none and requires capability plus serving support;
merge-only has neither. A referenced definition is immutable: disable and
create a new behavior-named flow, retain history:

```bash
yoke deployment-flows set-status {flow_id} disabled
```

### Hosting deferred/not-needed: create the confirmed merge-only default

Only confirmed merge-only: no site/environment/excluded Pack. Omit target-tier
and environment on create; two auto stages record local merge without a run:

```bash
yoke deployment-flows create {project}-merge-only --project {project} --name "{project} merge-only" --stages-json '[{"name":"merged","step_runner":"auto"},{"name":"complete","step_runner":"auto"}]'
yoke deployment-flows get {project}-merge-only target_tier
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"deploy_defaults","attachment":"project","payload":{"deployment_flow":"{project}-merge-only"}}]'
yoke workflows delivery-default set --project {project} --workflow dash --flow {project}-merge-only
yoke workflows delivery-default set --project {project} --workflow issue --flow {project}-merge-only
yoke workflows delivery-default set --project {project} --workflow epic --flow {project}-merge-only
yoke workflows delivery-default set --project {project} --workflow blitz --flow {project}-merge-only
yoke project-structure deploy-defaults get --project {project}
yoke workflows mechanics get --json
```

The target-tier read must print nothing; default exactly the registered flow.
Conflicting immutable ID: disable, create a new behavior-named flow, use its ID.
Merge-only discharges delivery at merge; walk every pinned stage/gate including
release wait to done with no deployment run. Verify both reads/all four defaults:

```bash
yoke onboard checklist --run-id {run_id} --row-status environment-registration=not-needed --evidence environment-registration="live no-host row; no managed registrations" --row-status delivery-setup=configured --evidence delivery-setup="active merge-only default; empty tier/all defaults verified; no deployment run"
```

### Hosting deferred/not-needed: clear the project default

Only when confirmed delivery outcome is **no default**. Preserve environment/
flow history; read, remove a nonempty attachment, read again; the final read must print nothing.
Never execute managed or merge-only put recipes in this branch:

```bash
yoke project-structure deploy-defaults get --project {project}
yoke project-structure patch apply --project {project} --ops-json '[{"op":"remove","family":"deploy_defaults","attachment":"project"}]'
yoke project-structure deploy-defaults get --project {project}
yoke onboard checklist --run-id {run_id} --row-status environment-registration=not-needed --evidence environment-registration="live no-host row; no managed registrations" --row-status delivery-setup=not-needed --evidence delivery-setup="project default verified empty; no persistent route assigned"
```

Removal/readback failure: delivery-setup=blocked with exact command/error/recovery,
then stop. Do not seed against an unverified default.

### Bind the confirmed test setup

Follow [verification-binding.md](verification-binding.md), independent of host.
[governed-database.md](governed-database.md) similarly owns the database answer.

### Project Structure policies and optional architecture

Use one keyed `put` operation per surveyed test tree; all roots descriptive,
quick may cover a slice and full the aggregate. Context routing, ownership
and integration targets use the same patch surface.

```bash
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"test_roots","attachment":"{test_root}","entry_key":"{root_key}","payload":{"purpose":"{suite_purpose}"}}]'
```

Offer scan → draft → operator edit/accept → patch for architecture. Empty repos
receive minimal vocabulary and future unclassified warning; skipping is valid.

```bash
yoke project snapshot sync {checkout} --project {project}
yoke project-structure architecture-draft get --project {project}
```

Insert accepted **complete JSON** through project_structure.patch.apply's
architecture_model/project put; no placeholder fragment is executable. Same
schema/patch contract as the policy recipe above. Verify architecture-health;
snapshot sync thereafter refreshes classification.

Managed branch: environment-registration and delivery-setup configured (verified
for already-satisfied facts), names actual site/environments/flows/default.
Both branches: project-structure-setup configured/verified names policy families/
architecture coverage. Rejected validation/create/register/Pack/cleanup blocks
the matching row with error/recovery; stop, retain completed registrations.
Next: [domain-and-deploy.md](domain-and-deploy.md).
