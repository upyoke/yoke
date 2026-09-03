# Onboard Steps 4–5: Hosting Capability And Environment Registration

Step 4 verifies (or connects) the hosting capability. Step 5 installs only the confirmed infra Packs and then either registers managed hosting routes or applies the confirmed merge-only/no-default delivery choice. Both branches are registration/verification only — **no cloud mutation happens here**; every cloud write waits behind the approval gate in step 7.

## Step 4: Hosting Capability

- **Entry:** the project has not declared that Yoke manages no host.
- **Skip:** the declared posture is `no-yoke-managed-host`, or the `aws-admin` capability is present AND the live identity probe passes (redacted evidence only) — the latter being the normal case when hosting was connected during wire-up.
- **Rows:** `hosting-setup`, `capability-setup`.

### Read the declared posture first

A project can say that its hosting is somebody else's job. Read that before asking for anything:

```bash
yoke project-structure get --project {project} --family hosting_posture --json
```

A payload of `{"posture": "no-yoke-managed-host"}` settles the row without a credential, a probe, or an `aws-admin` capability. Mark it and move straight to `capability-setup`:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status hosting-setup=not-needed \
  --evidence hosting-setup="project declares no Yoke-managed host (runs on {provider}); no cloud credential requested"
```

`not-needed` and `deferred` are different answers and must stay that way: the first is a decision the operator made, the second is a question still open. Never mark a declared posture `deferred`, and never ask for AWS credentials on top of one — that is the failure this declaration exists to prevent.

An empty read means the question is still open. Ask it once here, record the answer through the same family so the next run does not ask again, then continue down the matching branch:

```bash
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"hosting_posture","attachment":"project","payload":{"posture":"no-yoke-managed-host","provider":"{where it runs}"}}]'
```

Use `"posture": "aws-admin"` for the branch where Yoke manages AWS hosting. `provider` is optional prose recording where the code actually runs; Yoke never acts on it.

### Establish the AWS CLI before anything else on this branch

Every capability-owned AWS operation — the identity probe below, the infra Packs' own tooling, `yoke aws exec`, `yoke vps` — shells out to the `aws` executable. Storing a credential proves nothing about whether this machine has one, so check it before you probe an existing capability and before you ask an operator to create a key:

```bash
yoke aws preflight
```

A refusal names which of the three failures happened — not installed, installed off `PATH`, or present but unusable — and carries the install or `PATH` recovery for this machine. Do not continue down this branch, do not ask for an access key pair, and never record `hosting-setup=configured|verified` on a machine that cannot run the CLI. Mark the row blocked with what the refusal said, and stop:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status hosting-setup=blocked \
  --blocker hosting-setup="AWS CLI prerequisite refused ({code}); recovery: {recovery line from the refusal}; then re-run /yoke onboard --run-id {run_id}"
```

The operator's hosting answer survives that block: it is a missing prerequisite, not a change of mind, so do not rewrite the posture row or propose the no-managed-host branch instead.

### Read both halves before asking for anything

`aws-admin` is two facts, not one. The capability row lives in the connected control plane and carries the non-secret settings (`region`, and `account_id` once an identity probe has named it); the access-key pair lives only on this machine under the capability secret store. A deploy needs both, each is filled by a different command, and **either can be present without the other** — a wizard run that stored the pair on a machine whose project row was never registered leaves the credential on disk and the row absent. Asking for the two secret values again would be asking the operator to re-enter what is already saved.

With the prerequisite established, read both halves in one call. It names the missing half and only the command that fills that half:

```bash
yoke aws admin-status --project {project} --json
```

`ready: true` → prove it live. The probe runs the AWS CLI with the project's `aws-admin` credentials materialized by the capability resolver into the subprocess env only — nothing is exported into the shell and no secret value is ever printed:

```bash
yoke aws exec --project {project} -- sts get-caller-identity --output json
```

Both pass → mark and skip:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status hosting-setup=verified \
  --evidence hosting-setup="aws-admin row + machine credential pair present; identity probe passed (account {redacted_account}, arn type only)"
```

Ready but the probe fails → the stored credentials are stale or wrong (not missing). Surface as blocked with the re-set recipe; do not guess or retry with ambient shell credentials:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status hosting-setup=blocked \
  --blocker hosting-setup="aws-admin row + credential pair present but identity probe failed; re-set via: yoke projects capability secret set --project {project} --cap-type aws-admin --key access_key_id --value-stdin (and --key secret_access_key), then re-run /yoke onboard --run-id {run_id}"
```

### Fill only the missing half

`ready: false` names `missing` as `capability_row`, `machine_secrets`, or both, and `remedy` carries the exact command per missing half. Run only those; never a command for a half the report says is present.

- `missing: ["capability_row"]` — the pair is already on this machine and the project simply has no row. Register it with the settings merge, which creates an absent capability and CAS-updates an existing one, so re-running converges:

  ```bash
  yoke projects capability-settings merge --project {project} --cap-type aws-admin --set region={region}
  ```

  Do not ask for the access key again, and do not reach for `capability-settings set --key ... --value ...` — settings are one JSON document per capability and that flag pair does not exist there. `--key` belongs to the secret surface below.

- `missing: ["machine_secrets"]` (or both halves) — creating cloud credentials is always user-action plus explicit approval, and the AWS CLI preflight above has to pass first — a key created for a machine that cannot run the CLI is an unusable credential the operator has to rotate later. Guide the operator to create the access key pair in their own provider console; the two values go into the terminal `--value-stdin` prompts — **never into the chat**. Import only the keys the report listed as missing:

  ```bash
  yoke projects capability secret set --project {project} --cap-type aws-admin --key access_key_id --value-stdin
  yoke projects capability secret set --project {project} --cap-type aws-admin --key secret_access_key --value-stdin
  ```

Non-secret settings live on the project capability; secret material lands only in the machine-local capability secret store. Re-run `yoke aws admin-status` until `ready: true`, verify with the same identity probe above, then mark `hosting-setup=configured` with redacted evidence and record the matching posture (`"posture": "aws-admin"`) so later runs skip the question. The operator may instead defer hosting entirely (`hosting-setup=deferred` with the reason, writing no posture row); step 7 then stays unreachable and step 8 still runs.

### Remaining capabilities

Verify the rest of the confirmed profile's capabilities:

- **GitHub binding mode.** Record the project's mode — `app-binding` (bind the exact repository selected from the machine's GitHub App installation access) or `disabled` (GitHub automation disabled until an App installation can see the repository with the required permissions). The operator authorizes the machine through `yoke github connect`; onboarding never asks for, stores, or promotes a GitHub token. An App binding is active only when the selected repository belongs to a non-suspended installation with all required repository permissions; otherwise preserve the binding as pending and keep the project in `disabled`. Check with:

```bash
yoke github status --json
```

- **Product-specific keys** the profile names: same `capability has` check, same `capability secret set --value-stdin` import, redacted evidence only.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status capability-setup=configured \
  --evidence capability-setup="github mode {mode}; capabilities verified: {cap types}; secrets imported by key name only"
```

**Failure floor:** missing operator input or console access → mark the specific row `blocked` with what is needed; stop.

## Step 5: Infra Packs + Hosted Registration Or No-Host Cleanup

- **Entry:** scaffold present (installed or mapped); the durable checklist says `hosting-setup=verified|configured|deferred|not-needed`.
- **Skip:** re-read the live hosting row. For `verified|configured`, the site, environments, persistent flows, project default, and test binding must match the profile. For `deferred|not-needed`, the confirmed delivery choice must be verified as either a registered merge-only default or an empty default, and the no-host terminal rows, independent test binding, and Project Structure policy work must match. Packs in `.yoke/packs.json` skip individually.
- **Rows:** `environment-registration`, `project-structure-setup`, `delivery-setup`, `verification-command-binding`.

Prior `deferred` or `not-needed` values are not proof that a later hosting-required profile is satisfied. Every rerun reads `yoke onboard checklist --run-id {run_id} --json` and re-evaluates the live capability probe, registrations, project default, and deployment health. Choose exactly one branch below from the current `hosting-setup` value; a partial managed-host failure never falls through to the no-host branch.

### Install the infra Packs

Same receipt-first, preview-then-apply mechanics as the scaffold (see [profile-and-scaffold.md](profile-and-scaffold.md)) for each infra/deploy Pack in the confirmed profile. A no-host profile never gains an excluded infra/deploy Pack merely to satisfy this step:

```bash
yoke packs get {pack} {checkout} --project {project}
yoke packs get {pack} {checkout} --project {project} --apply
```

Installing a Pack lands source in the repo only — its stacks do not run until step 7's gate.

### Hosting verified/configured: register the site and environments

Only this branch may register managed hosting. Registration is idempotent: an existing row with the same identity reports already-present and is never overwritten.

```bash
yoke projects site create --project {project} --site {site_name}
yoke projects environment create --project {project} --site {site_name} --environment stage
yoke projects environment create --project {project} --site {site_name} --environment prod
```

Discover what already exists with the metadata-only inventory (`yoke projects infrastructure list --project {project} --json`). Read environment configuration only through explicit scalar leaf projections (`yoke projects environment-settings get --project {project} --environment {environment} --path {key.path} --json`); never dump an environment settings document.

### Create The Persistent Deploy Flow And Default

Deployment flows are ordinary database rows. Create each one with a command; nothing in the project repo defines them.

If the checkout already carries deploy configuration of any shape — a CI workflow, a deploy script, an older `.yoke/deployment-flows.json` from a previous Yoke version — read it as a **hint** about the stages this project wants. Whatever shape it has is acceptable input and none of it is contractual: no schema, no version, no required keys. Such a file is the project's own, and may still have consumers inside its repository: do not author, migrate, repair, or delete one, and never make onboarding depend on one parsing.

Create one flow per route, then set the project default:

```bash
yoke deployment-flows create {flow_id} --project {project} --name "{flow_name}" \
  --stages-file {stages_path} --target-tier persistent --environment {environment}
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"deploy_defaults","attachment":"project","payload":{"deployment_flow":"{default_flow_id}"}}]'
yoke project-structure deploy-defaults get --project {project}
```

A persistent flow names exactly one registered environment; an ephemeral flow (`--target-tier ephemeral`) deploys per-run preview substrate and names none; a merge-only flow declares neither. Retire a route with `yoke deployment-flows set-status {flow_id} disabled` — a definition a run has referenced is immutable, so a changed route is a retirement plus a new flow, and history stays readable.

### Hosting deferred/not-needed: create the confirmed merge-only default

Use this branch only when the confirmed delivery outcome is **merge-only**. Create no site or environment, install no excluded infra/deploy Pack, and omit both `--target-tier` and `--environment`. The two auto stages record the local merge boundary without creating a deployment run:

```bash
yoke deployment-flows create {project}-merge-only --project {project} \
  --name "{project} merge-only" \
  --stages-json '[{"name":"merged","step_runner":"auto"},{"name":"complete","step_runner":"auto"}]'
yoke deployment-flows get {project}-merge-only target_tier
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"deploy_defaults","attachment":"project","payload":{"deployment_flow":"{project}-merge-only"}}]'
yoke project-structure deploy-defaults get --project {project}
```

The target-tier read must print nothing and the default readback must print exactly `{project}-merge-only`. If that id already exists with a different immutable definition, disable it and create a new behavior-named flow before setting the default. A failed create or readback marks `delivery-setup=blocked` with the exact command and recovery recipe below; stop rather than claiming merge-only delivery.

After both reads verify, record the no-environment registration and the runless default:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status environment-registration=not-needed \
  --evidence environment-registration="live hosting row {deferred|not-needed}; no managed site or environment registered" \
  --row-status delivery-setup=configured \
  --evidence delivery-setup="merge-only flow {project}-merge-only active; target tier empty; project default verified; no deployment run"
```

### Hosting deferred/not-needed: clear the project default

Use this branch only when the confirmed delivery outcome is **no default**. Do not run the managed-host registration or merge-only default-put recipes above. Existing environment and flow history stays intact, but new work must not route to it. Read the default; when the read is non-empty, remove the project attachment through the existing patch surface, then read it again. The final read must print nothing:

```bash
yoke project-structure deploy-defaults get --project {project}
yoke project-structure patch \
  apply --project {project} --ops-json '[{"op":"remove","family":"deploy_defaults","attachment":"project"}]'
yoke project-structure deploy-defaults get --project {project}
```

After an empty readback, record terminal evidence and continue with the independent test binding and Project Structure policy work below:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status environment-registration=not-needed \
  --evidence environment-registration="live hosting row {deferred|not-needed}; no managed site or environment registered" \
  --row-status delivery-setup=not-needed \
  --evidence delivery-setup="project default verified empty; no persistent route assigned"
```

If removal or empty readback fails, record the exact command and recovery, then stop. Do not seed work against an unverified default:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status delivery-setup=blocked \
  --blocker delivery-setup="{failed command}: {captured error}; repair access, then re-run /yoke onboard --run-id {run_id}"
```

### Bind the confirmed test setup

Read and follow [verification-binding.md](verification-binding.md). It owns
the whole verification binding: the registered command per scope, which
GitHub Actions workflow may be declared as this project's CI routing and
why an unreachable one is refused, when the merge queue may be offered, the
review-only and attested no-tests branches, and the
`verification-command-binding` checklist row each outcome writes.

### Project Structure policy rows

Capture the project-wide policy the profile implies — test roots, context
routing, ownership defaults, integration targets — through the registered patch
surface. These rows are descriptive project structure; the command the QA gate
runs is bound above, not here:

```bash
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"test_roots","attachment":"apps/api/tests/","entry_key":"api","payload":{"purpose":"API suite"}},{"op":"put","family":"test_roots","attachment":"apps/web/tests/","entry_key":"web","payload":{"purpose":"Web suite"}}]'
```

Use one keyed `put` operation per surveyed test tree. Multiple roots describe
the repository; they do not require `quick` to run every suite. The separately
registered `full` argv is where the broader aggregate belongs.

### Architecture map (scan-derive-accept; skippable)

Offer the project an architecture map: propose a draft from the tree, review it with the operator, and apply the edited result through the same patch surface — identical for every repo state (an empty repo yields the minimal vocabulary-only map that grows via the unclassified warning; a scaffolded repo is just a tidy tree the scanner classifies). Skipping is fine — the project adopts later with the same two commands.

```bash
yoke project snapshot sync {checkout} --project {project}
yoke project-structure architecture-draft get --project {project} > /tmp/architecture-draft.json
# review + edit the draft with the operator, then insert that JSON payload:
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"architecture_model","attachment":"project","payload":{architecture_model_json}}]'
```

Once applied, classifications refresh automatically on every snapshot sync; verify with `yoke project-structure architecture-health get --project {project}` and record the coverage line as evidence on the `project-structure-setup` row.

### Mark the managed-host and independent rows

For `hosting-setup=verified|configured`, mark the managed registrations:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status environment-registration=configured \
  --evidence environment-registration="site {site_slug} + stage/prod registered; flows created: {flow_ids}; default flow {flow_id}" \
  --row-status delivery-setup=configured \
  --evidence delivery-setup="sites, environments, and flows registered through commands"
```

On either branch, mark `project-structure-setup=configured` (or `verified` when already satisfied) with evidence naming the independent policy families applied. When a managed sub-part was already satisfied, use `verified` for its row instead of `configured`.

**Failure floor:** a rejected flow create, failed registration, failed Pack apply, or failed no-host cleanup → mark the matching row `blocked` with the error and recovery recipe; stop. Registrations already made stay (they are idempotent to re-run).

Continue to steps 6–7 of this skill: read [domain-and-deploy.md](domain-and-deploy.md).
