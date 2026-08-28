# Onboard Steps 2–3: Execution Profile And Scaffold Pack

Step 2 derives one complete execution profile from strategy plus reality and confirms it once — the first of the two stops. Step 3 begins the unattended applying run with the scaffold Pack.

## Step 2: Derive The Execution Profile

- **Entry:** strategy docs accepted.
- **Skip:** only when steps 3–8 all already satisfy their skip predicates (nothing left to apply). Otherwise always re-derive and re-confirm: **the confirmed profile is not persisted anywhere** — progress lives in the checklist rows, the profile does not. A resume re-derives the proposal from the strategy docs and the repo and re-confirms.
- **Row:** `human-interview`.

### Read the inputs

- The five strategy docs (step 1 output).
- The repo survey from step 1; in existing-repo mode, map surveyed artifacts onto the profile boxes (an existing app, CI, or infra counts toward the profile rather than being reinstalled).
- Recorded project state:

```bash
yoke packs list --project {project} --json
yoke project-structure get --project {project} --family hosting_posture --json
yoke projects capability has --project {project} --cap-type aws-admin --json
yoke projects infrastructure list --project {project} --json
yoke project-structure deploy-defaults get --project {project}
```

The hosting posture is read first because it decides half the profile. `{"posture": "no-yoke-managed-host"}` means the operator runs the hosting themselves: propose **no** `aws-admin` capability and **no** infra Packs, say so out loud with the recorded provider, and spend the conversation on what Yoke does do for them — merging, verification, delivery. Proposing a stock AWS list to a project that already said "not AWS" is the failure this read prevents. An empty result means the question is open; ask it once as part of the profile and record the answer (step 4 owns the write).

Also read the project-local `.yoke/packs.json` installed baseline (the receipt of already-installed Packs) and `.yoke/deployment-flows.json` if present.

### Propose one complete profile

Present the whole profile in one block — a smart proposal, never a blank interrogation:

- **Packs** — name each one with the provider it actually targets, so nobody adopts a Pack that cannot run where their code runs:
  - scaffold — `webapp-scaffold` (provider-neutral application skeleton)
  - infra — `pulumi-foundation` (Pulumi state/stack setup) · `vps-hosting` (**AWS EC2**: instance, networking, TLS, firewall) · `webapp-environment-infrastructure` (**AWS** environment resources)
  - deploy — `registry-oidc` (**AWS** OIDC federation for CI) · `production-deploy` (deploy pipeline onto the above)
  - any documentation/context Packs the plan needs (provider-neutral)

  Every infra and deploy Pack above targets AWS. Under a `no-yoke-managed-host` posture, propose none of them and say why — Yoke has no apply path for Render, Fly, DigitalOcean, dokku, or an on-prem box, and offering an AWS Pack to a project hosted elsewhere is offering something that cannot run. Drop what strategy does not justify; an existing app maps instead of installing a scaffold.
- **Capabilities** — `aws-admin` (hosting; omit entirely under `no-yoke-managed-host`), the project GitHub binding mode, product-specific keys named by the plan.
- **Delivery** — exactly one named outcome from the delivery box below.
- **Domain posture** — start on the default subdomain; bring-your-own later.
- **Test setup** — how this project's tests run, and therefore what the
  `reviewing-implementation` gate will execute. See the box below.
- **CI routing** — whether a GitHub Actions workflow runs that command, and
  therefore whether the gate runs in CI or on this machine. Propose a
  `ci_workflow_file` declaration only for the **test** workflow the step-1
  survey classified as running the suite; never a deploy, release, or
  artifact-build workflow, and never a Jenkins, GitLab, Bitbucket, or
  `fastlane` job. Those keep the local `command` runner, which is a correct
  configuration. Propose the merge queue only when GitHub is bound, that test
  workflow is declared, and it carries a `merge_group` trigger — without the
  trigger the queue's integration gate has nothing to run and a queued pull
  request never merges.

### The delivery box

Every profile names exactly one delivery outcome:

1. **Persistent environment** — a registered environment plus a pipeline flow. This is legal only when hosting is `verified` or `configured`.
2. **Merge-only** — local merge with no environment and no deployment pipeline or run.
3. **No default** — new items omit `--deployment-flow` until the project chooses delivery later.

When hosting is `deferred` or `not-needed`, offer only merge-only or no default. The confirmation evidence must spell out the chosen name and meaning; never silently turn a no-host profile into stage + prod.

### The test-setup box

Every profile carries this box. It is never omitted and never inferred
silently, because the gate that blocks `reviewing-implementation` runs the
project's **registered verification command**, and a project that never
declares one reaches that gate with nothing to run.

Propose exactly one of four named outcomes, from the step 1 repo survey:

1. **A surveyed command.** The survey found a real suite — a `pytest`
   invocation, `mvn -q -DskipITs test`, `vendor/bin/phpunit --testsuite unit`,
   `xcodebuild test`, `docker compose run --rm tests`, or whatever the repo
   actually runs. Propose a reliable documented slice as `quick`, and a
   broader argv as `full` when the two genuinely differ. Preserve every
   surveyed test tree as a separate `test_roots` entry; a monorepo may have
   several roots even when one quick command is the routine gate. Propose the
   argv the repo runs; never invent one or require it to look like pytest.
2. **A scaffold suite.** The profile installs a scaffold Pack that lands
   tests — `webapp-scaffold` ships FastAPI tests, Vitest, Playwright
   examples, and `.github/workflows/ci.yml`. Propose the Pack's own test
   command, and note that its workflow becomes the CI declaration in step 5.
3. **A review-only suite.** A known-red or materially flaky legacy suite is
   real evidence but cannot honestly be the blocking registered command yet.
   Preserve its roots, exact argv, and known condition in the profile. Do not
   bind it as `quick`, `full`, or `command-ci`; step 8 seeds a blocking
   `implementation_review` plus a non-blocking `command` requirement so the
   current result is recorded without manufacturing a green gate.
4. **No suite at all.** The step-1 survey found nothing runnable — an
   idea-only repo, a content site, a client who will not pay for tests yet.
   Offer exactly three named choices, in this order, and never a fabricated
   `pytest`, CI declaration, or merge queue:

   1. **Scaffold a minimal suite.** `webapp-scaffold` for a greenfield or
      empty application repo; a one-file project-native suite for a
      content-only or pre-code repo. Recommend this first — a project with
      one real test has a real gate.
   2. **Attest no-tests.** The operator declines a suite and says why. Step 5
      records that reason as a durable project row, and from then on the
      `reviewing-implementation` transition seeds a blocking
      `implementation_review` requirement where the registered command would
      have run. This is a decision, not an omission: an empty gate reports
      green for a review nobody performed.
   3. **Stop.** The operator has not decided. Nothing is written; the profile
      cannot be confirmed with the box unanswered, so this is the existing
      failure floor — `human-interview=blocked` with the open question as
      blocker text.

A descriptive `verification_profiles.test_command` project-structure entry is
**not** one of these outcomes. It records what the project's tests are for a
human reader; it is not consulted by the gate. Writing it and stopping leaves
the project exactly as unbound as writing nothing.

### Confirm (stop 1 of 2)

The operator confirms or adjusts the whole profile; edits refine the proposal in place. **Nothing mutates before this confirmation.** This confirmation also closes the interview — every remaining unknown is resolved here or recorded as a blocker. Then mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status human-interview=verified \
  --evidence human-interview="execution profile confirmed: {packs}; capabilities {caps}; delivery {persistent-environment|merge-only|no-default}: {registered environment plus pipeline|local merge, no environment or pipeline|new items omit --deployment-flow}; domain {posture}; test setup {surveyed-command|scaffold-suite|review-only-suite|attested-no-tests}; roots {test_roots}; quick {quick_argv|not-applicable}; full {full_argv|same-as-quick|not-applicable}; suite health {suite_health}; runner {command|command-ci|review-only|none} because {runner_rationale}"
```

After confirmation, run steps 3–6 straight through unattended. The next stop is the infrastructure approval gate in step 7.

**Failure floor:** unresolved profile unknowns (unclear deploy target, unnamed required credential, an undecided test-setup box) → `human-interview=blocked` with the open questions as blocker text; stop.

## Step 3: Install The Scaffold Pack

- **Entry:** confirmed profile includes a scaffold Pack. An existing app maps instead of installing — record the mapping and move on.
- **Skip:** the `.yoke/packs.json` receipt already records the Pack → report the installed version and skip. Version moves are `yoke packs update`, not onboarding.
- **Rows:** `scaffold-install`, `documentation-context-setup`.

### Receipt-first skip check

Read the installed baseline before touching the Pack surface:

```bash
cat {checkout}/.yoke/packs.json
```

If the scaffold Pack appears there, mark the row and skip the install:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status scaffold-install=verified \
  --evidence scaffold-install="webapp-scaffold {version} already installed per .yoke/packs.json receipt"
```

### Preview, then apply

Pack installs are preview-first. Preview against the target checkout, inspect the file plan, then apply the same command:

```bash
yoke packs get webapp-scaffold {checkout} --project {project}
yoke packs get webapp-scaffold {checkout} --project {project} --apply
```

Pack output becomes ordinary project-owned source — customization is expected — and `.yoke/packs.json` records the applied baseline for independent future updates. Do not force conflicts; a preview conflict against existing files means existing-repo mapping, not overwrite. Commit the applied files in the project repo.

Mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status scaffold-install=configured \
  --evidence scaffold-install="webapp-scaffold {version} installed; receipt recorded in .yoke/packs.json"
```

For the mapped-existing-app case, mark `scaffold-install=not-needed` with the mapping as evidence (which existing surfaces cover the scaffold's role).

### Documentation/context Packs

If the confirmed profile includes documentation/context Packs (runbooks, context routing), install them through the same preview-then-apply surface and mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status documentation-context-setup=configured \
  --evidence documentation-context-setup="context/runbook Packs installed: {packs}"
```

When the profile includes none, mark `documentation-context-setup=not-needed` with a one-line reason.

**Failure floor:** a failed preview or apply → `scaffold-install=blocked` with the conflict or error as blocker text; stop. Applied files from a completed apply stay in place.

Continue to steps 4–5 of this skill: read [hosting-and-environments.md](hosting-and-environments.md).
