# Onboard Steps 4–5: Hosting Capability And Environment Registration

Step 4 verifies (or connects) the hosting capability. Step 5 installs the infra Packs and registers environments, sites, and the default deploy flow. Both are registration/verification only — **no cloud mutation happens here**; every cloud write waits behind the approval gate in step 7.

## Step 4: Hosting Capability

- **Entry:** the confirmed profile requires hosting.
- **Skip:** `aws-admin` capability present AND the live identity probe passes (redacted evidence only) — the normal case when hosting was connected during wire-up.
- **Rows:** `hosting-setup`, `capability-setup`.

### Skip probe

Check the capability row, then prove it live. The probe runs the AWS CLI with the project's `aws-admin` credentials materialized by the capability resolver into the subprocess env only — nothing is exported into the shell and no secret value is ever printed:

```bash
yoke projects capability has --project {project} --cap-type aws-admin --json
yoke aws exec --project {project} -- sts get-caller-identity --output json
```

Both pass → mark and skip:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status hosting-setup=verified \
  --evidence hosting-setup="aws-admin present; identity probe passed (account {redacted_account}, arn type only)"
```

Capability row present but the probe fails → the stored credentials are stale or wrong. Surface as blocked with the re-set recipe; do not guess or retry with ambient shell credentials:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status hosting-setup=blocked \
  --blocker hosting-setup="aws-admin present but identity probe failed; re-set via: yoke projects capability secret set --project {project} --cap-type aws-admin --key access_key_id --value-stdin (and --key secret_access_key), then re-run /yoke onboard --run-id {run_id}"
```

### Connect (only when the capability is absent)

Creating cloud credentials is always user-action plus explicit approval. Guide the operator to create the access key pair in their own provider console; the two values go into the terminal `--value-stdin` prompts — **never into the chat**:

```bash
yoke projects capability secret set --project {project} --cap-type aws-admin --key access_key_id --value-stdin
yoke projects capability secret set --project {project} --cap-type aws-admin --key secret_access_key --value-stdin
yoke projects capability-settings set --project {project} --cap-type aws-admin --key region --value {region}
```

Non-secret settings live on the project capability; secret material lands only in the machine-local capability secret store. Verify with the same identity probe above, then mark `hosting-setup=configured` with redacted evidence. The operator may instead defer hosting entirely (`hosting-setup=deferred` with the reason); step 7 then stays unreachable and step 8 still runs.

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

## Step 5: Infra Packs + Environments, Sites, Deploy Flow

- **Entry:** scaffold present (installed or mapped); hosting verified or explicitly deferred.
- **Skip:** registrations already match the profile → skip; Packs already in the `.yoke/packs.json` receipt skip individually.
- **Rows:** `environment-registration`, `project-structure-setup`, `delivery-setup`, `verification-command-binding`.

### Install the infra Packs

Same receipt-first, preview-then-apply mechanics as the scaffold (see [profile-and-scaffold.md](profile-and-scaffold.md)) for each infra/deploy Pack in the confirmed profile:

```bash
yoke packs get {pack} {checkout} --project {project}
yoke packs get {pack} {checkout} --project {project} --apply
```

Installing a Pack lands source in the repo only — its stacks do not run until step 7's gate.

### Register the site and environments

Registration is idempotent: an existing row with the same identity reports already-present and is never overwritten.

```bash
yoke projects site create --project {project} --site {site_name}
yoke projects environment create --project {project} --site {site_name} --environment stage
yoke projects environment create --project {project} --site {site_name} --environment prod
```

Discover what already exists with the metadata-only inventory (`yoke projects infrastructure list --project {project} --json`). Read environment configuration only through explicit scalar leaf projections (`yoke projects environment-settings get --project {project} --environment {environment} --path {key.path} --json`); never dump an environment settings document.

### Create the deploy flows and the default

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

### Bind the confirmed test setup

This applies the test-setup box the operator confirmed in step 2. It runs here,
after the scaffold Pack has landed its tests and its `.github/workflows/ci.yml`,
so the declaration describes files that actually exist.

**A surveyed command or a scaffold suite** binds in one call per scope:

```bash
yoke qa registered-command set --project {project} --scope quick --command "{quick_argv}"
```

Add the `full` scope only when its argv genuinely differs from `quick`:

```bash
yoke qa registered-command set --project {project} --scope full --command "{full_argv}"
```

One call converges the whole binding — the `registered-command-{scope}` plan,
its case row, the runner the case uses, and the project-default attachments at
the transitions that gate. It needs no environment, because a command case runs
in the item's worktree or in CI, never against a site behind a base URL.

**When a GitHub Actions workflow runs that command**, declare it first, so the
binding above routes the case to CI instead of the local runner:

```bash
yoke projects capability-settings set --project {project} --cap-type ci_workflow_file \
  --new --settings-json '{"workflow_file":"{ci_yml_filename}"}'
```

Name the **test** workflow — the one that runs the registered command. A deploy
or release workflow is not a verification workflow; declaring one there makes
the gate report a green that proves nothing. With no declaration the scopes keep
the local `command` runner, which is a correct outcome, not a downgrade.

**An explicit skip** registers nothing. Record the decision and move on; the
`reviewing-implementation` gate falls back to the `implementation_review`
requirement that advance seeds when no plan and no acceptance criteria exist.

A `verification_profiles.test_command` entry in the policy rows below is
descriptive only. It is never read by the gate, so writing it is not a
substitute for the binding above.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status verification-command-binding=configured \
  --evidence verification-command-binding="registered-command-quick bound to {quick_argv}; runner {command|command-ci}; {ci_workflow_file or 'no Actions test workflow declared'}"
```

For the explicit skip, mark `verification-command-binding=not-needed` with the
operator's reason as evidence. When the operator has not decided yet, mark it
`deferred`; when the argv cannot be verified against the repo, mark it
`blocked` with the missing executable named.

### Project Structure policy rows

Capture the project-wide policy the profile implies — test roots, context
routing, ownership defaults, integration targets — through the registered patch
surface. These rows are descriptive project structure; the command the QA gate
runs is bound above, not here:

```bash
yoke project-structure patch apply --project {project} --ops-json '{json_ops}'
```

### Architecture map (scan-derive-accept; skippable)

Offer the project an architecture map: propose a draft from the tree, review it with the operator, and apply the edited result through the same patch surface — identical for every repo state (an empty repo yields the minimal vocabulary-only map that grows via the unclassified warning; a scaffolded repo is just a tidy tree the scanner classifies). Skipping is fine — the project adopts later with the same two commands.

```bash
yoke project snapshot sync {checkout} --project {project}
yoke project-structure architecture-draft get --project {project} > /tmp/architecture-draft.json
# review + edit the draft with the operator, then insert that JSON payload:
yoke project-structure patch apply --project {project} --ops-json '[{"op":"put","family":"architecture_model","attachment":"project","payload":{architecture_model_json}}]'
```

Once applied, classifications refresh automatically on every snapshot sync; verify with `yoke project-structure architecture-health get --project {project}` and record the coverage line as evidence on the `project-structure-setup` row.

### Mark the rows

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status environment-registration=configured \
  --evidence environment-registration="site {site_slug} + stage/prod registered; flows created: {flow_ids}; default flow {flow_id}" \
  --row-status project-structure-setup=configured \
  --evidence project-structure-setup="policy rows applied: {families}" \
  --row-status delivery-setup=configured \
  --evidence delivery-setup="sites, environments, and flows registered through commands"
```

When a sub-part was already satisfied, use `verified` for that row instead of `configured`.

**Failure floor:** a rejected flow create, failed registration, or failed Pack apply → mark the matching row `blocked` with the error and recovery recipe; stop. Registrations already made stay (they are idempotent to re-run).

Continue to steps 6–7 of this skill: read [domain-and-deploy.md](domain-and-deploy.md).
