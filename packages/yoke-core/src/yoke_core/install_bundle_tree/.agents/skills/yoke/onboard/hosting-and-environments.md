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
- **Rows:** `environment-registration`, `project-structure-setup`, `delivery-setup`.

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
yoke projects site create --project {project} --site-slug {site_slug}
yoke projects environment create --project {project} --site-slug {site_slug} --environment-id stage
yoke projects environment create --project {project} --site-slug {site_slug} --environment-id prod
```

Discover what already exists with the metadata-only inventory (`yoke projects infrastructure list --project {project} --json`). Read environment configuration only through explicit scalar leaf projections (`yoke projects environment-settings get --project {project} --environment-id {environment_id} --path {key.path} --json`); never dump an environment settings document.

### Declare the deploy flows and the default

The deploy-flow surface is declaration-driven. Write the project-owned declaration to `.yoke/deployment-flows.json` in the checkout (schema 3: `flows` with `id`/`name`/`description`/`stages`/`on_failure`/`target_tier`/`target_environment_id`/`done_description`/`status`, plus top-level `default_flow`), then reconcile — the declared `default_flow` also sets the project deploy default:

```bash
yoke deployment-flows reconcile-project {project} {checkout}/.yoke/deployment-flows.json
yoke project-structure deploy-defaults get --project {project}
```

Reconcile converges only the declared definitions and leaves omitted rows untouched. Commit the declaration file in the project repo.

### Project Structure policy rows

Capture the project-wide policy the profile implies (command definitions, merge verification, context routing) through the registered patch surface:

```bash
yoke project-structure patch apply --project {project} --ops-json '{json_ops}'
```

### Architecture map (scan-derive-accept; skippable)

Offer the project an architecture map: propose a draft from the tree, review it with the operator, and apply the edited result through the same patch surface — identical for every repo state (an empty repo yields the minimal vocabulary-only map that grows via the unclassified warning; a scaffolded repo is just a tidy tree the scanner classifies). Skipping is fine — the project adopts later with the same two commands.

```bash
yoke project snapshot sync {checkout} --project {project}
yoke project-structure architecture-draft get --project {project} > /tmp/architecture-draft.json
# review + edit the draft with the operator, then apply it as the
# architecture_model family via `yoke project-structure patch apply`
```

Once applied, classifications refresh automatically on every snapshot sync; verify with `yoke project-structure architecture-health get --project {project}` and record the coverage line as evidence on the `project-structure-setup` row.

### Mark the rows

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status environment-registration=configured \
  --evidence environment-registration="site {site_slug} + stage/prod registered; flow declaration reconciled; default flow {flow_id}" \
  --row-status project-structure-setup=configured \
  --evidence project-structure-setup="policy rows applied: {families}" \
  --row-status delivery-setup=configured \
  --evidence delivery-setup="sites, environments, and flows registered through declared surfaces"
```

When a sub-part was already satisfied, use `verified` for that row instead of `configured`.

**Failure floor:** a rejected declaration, failed registration, or failed Pack apply → mark the matching row `blocked` with the error and recovery recipe; stop. Registrations already made stay (they are idempotent to re-run).

Continue to steps 6–7 of this skill: read [domain-and-deploy.md](domain-and-deploy.md).
