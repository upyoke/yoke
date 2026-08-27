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

Non-secret settings live on the project capability; secret material lands only in the machine-local capability secret store. Verify with the same identity probe above, then mark `hosting-setup=configured` with redacted evidence and record the matching posture (`"posture": "aws-admin"`) so later runs skip the question. The operator may instead defer hosting entirely (`hosting-setup=deferred` with the reason, writing no posture row); step 7 then stays unreachable and step 8 still runs.

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

The command value is the repo's exact shell argv, not a pytest-shaped field.
Maven, PHPUnit, XCTest, and containerized suites are ordinary examples:
`mvn -q -DskipITs test`, `vendor/bin/phpunit --testsuite unit`,
`xcodebuild test -scheme App`, or `docker compose run --rm tests`. Keep a
fast reliable slice in `quick`; bind the broader invocation separately as
`full` rather than pretending the same command represents both scopes.

One call converges the whole binding — the `registered-command-{scope}` plan,
its case row, the runner the case uses, and the project-default attachments at
the transitions that gate. `quick` and `full` are project-targeted: omit both
target flags even when the project has one or more environments. They run from
the project source in the item's worktree or in CI.

For local `e2e` and `smoke`, select exactly one deployed target contract:

```bash
yoke qa registered-command set --project {project} --scope e2e --command "{e2e_argv}" --environment {site}/{environment}
yoke qa registered-command set --project {project} --scope smoke --command "{smoke_argv}" --requires-base-url
```

The first binds a declared environment. The second requires the case runner to
supply an HTTP(S) `--base-url`. When `scope_workflows` routes either deployed
scope through CI, `--environment` is required and `--requires-base-url` is
refused. Registration validates the combination before writing the plan.

**Only when a GitHub Actions test workflow runs that command**, declare it
first, so the binding above routes the case to CI instead of the local runner:

```bash
yoke projects capability-settings set --project {project} --cap-type ci_workflow_file \
  --new --settings-json '{"workflow_file":"{ci_yml_filename}"}'
```

Name the **test** workflow — the one that runs the registered command. A deploy
or release workflow is not a verification workflow; declaring one there makes
the gate report a green that proves nothing. Jenkins, GitLab CI, Bitbucket
Pipelines, `fastlane`, and an XCTest or container command without a matching
Actions test workflow are not `ci_workflow_file`; keep those scopes on the
local `command` runner. With no declaration the scopes keep that runner, which
is a correct outcome, not a downgrade.

The binding refuses a workflow the gate cannot reach, and names why. The gate
starts a workflow by dispatching it with a `yoke_dispatch_id` input, so the
workflow must declare:

```yaml
on:
  pull_request:
  workflow_dispatch:
    inputs:
      yoke_dispatch_id:
        required: false
        default: ""
```

Without the `workflow_dispatch` input the gate cannot start a run at all and
registration refuses. Without `pull_request` the gate still works by
dispatching, but pays a second suite on every run instead of reusing the pull
request's own — and a project landing through the merge queue is refused
outright, because the queue lands only through pull requests. Where this
machine holds no checkout for the project the declaration cannot be read, and
the result says so rather than guessing.

Offer the merge queue only when all three hold: GitHub is bound, that test
workflow is declared, and it carries `merge_group:` among its `on` triggers.
Creating the row enforces the first two and reads the third from the workflow;
each missing piece refuses by name.

```bash
yoke projects capability-settings set --project {project} --cap-type merge_queue \
  --new --settings-json '{}'
```

**A review-only suite** registers no project-default command. Carry its test
roots, exact legacy argv, and known-red or flaky condition into step 8. Each
seeded item then gets a blocking `implementation_review` requirement plus a
non-blocking `command` requirement for the declared argv. This records the
suite's current result without letting it manufacture either a green gate or a
permanent blocking failure.

**An attested no-tests posture** records the decision as a project row rather
than leaving it as an omission:

```bash
yoke qa no-tests attest --project {project} --reason "{why this project has no suite to bind}"
```

The reason is required — it is what makes the row an attestation, and it is
what the reviewer reads at the gate to learn why no command ran. One call
records the posture and retires any `registered-command-*` plan the project
already had, so the two declarations can never both stand. From then on the
`reviewing-implementation` transition seeds a blocking `implementation_review`
requirement where `registered-command-quick` would have attached, and
registering any command — the `command-ci` runner included — is refused by
name until the posture is cleared with `yoke qa no-tests clear --project
{project} --reason "{what changed}"`.

A `verification_profiles.test_command` entry in the policy rows below is
descriptive only. It is never read by the gate, so writing it is not a
substitute for the binding above.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status verification-command-binding=configured \
  --evidence verification-command-binding="roots {test_roots}; quick {quick_argv}; full {full_argv|same-as-quick}; suite health {suite_health}; runner {command|command-ci} because {runner_rationale}; {ci_workflow_file or 'no Actions test workflow declared'}"
```

For an attested no-tests posture, mark `verification-command-binding=configured`
with the attestation as evidence — something was written down, and a later
reader must be able to tell an attested project from one nobody asked. Reserve
`not-needed` for a project that genuinely has nothing to bind and nothing to
attest, and `deferred` for the operator who has not decided yet. When the argv
cannot be verified against the repo, mark it `blocked` with the missing
executable named; the registration refuses that argv by name rather than
binding a gate that would fail wherever it ran.

For a review-only suite, mark `verification-command-binding=configured` with
evidence such as `review-only suite: roots {test_roots}; argv {legacy_argv};
suite health {known_condition}; runner advisory command because the suite is
not expected green; no project-default command; blocking implementation_review
plus advisory command requirements at seeding`.

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
