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
yoke projects capability has --project {project} --cap-type aws-admin --json
yoke projects infrastructure list --project {project} --json
yoke project-structure deploy-defaults get --project {project}
```

Also read the project-local `.yoke/packs.json` installed baseline (the receipt of already-installed Packs) and `.yoke/deployment-flows.json` if present.

### Propose one complete profile

Present the whole profile in one block — a smart proposal, never a blank interrogation:

- **Packs** — scaffold (`webapp-scaffold` for a web app); infra (`pulumi-foundation` · `vps-hosting` · `webapp-environment-infrastructure`); deploy (`registry-oidc` · `production-deploy`); any documentation/context Packs the plan needs. Drop what strategy does not justify; an existing app maps instead of installing a scaffold.
- **Capabilities** — `aws-admin` (hosting), the project GitHub binding mode, product-specific keys named by the plan.
- **Environments** — stage + prod on a default site, plus the default deploy flow for the slug.
- **Domain posture** — start on the default subdomain; bring-your-own later.
- **Test setup** — how this project's tests run, and therefore what the
  `reviewing-implementation` gate will execute. See the box below.

### The test-setup box

Every profile carries this box. It is never omitted and never inferred
silently, because the gate that blocks `reviewing-implementation` runs the
project's **registered verification command**, and a project that never
declares one reaches that gate with nothing to run.

Propose exactly one of three named outcomes, from the step 1 repo survey:

1. **A surveyed command.** The survey found a real suite — a `pytest`
   invocation, `npm test`, `go test ./...`, whatever the repo actually runs.
   Propose its argv as `quick`, and a broader argv as `full` when the two
   genuinely differ. Propose the argv the repo runs; never invent one, and
   never propose a command whose executable is absent from the repo.
2. **A scaffold suite.** The profile installs a scaffold Pack that lands
   tests — `webapp-scaffold` ships FastAPI tests, Vitest, Playwright
   examples, and `.github/workflows/ci.yml`. Propose the Pack's own test
   command, and note that its workflow becomes the CI declaration in step 5.
3. **An explicit skip.** The operator declines a suite — an idea-only repo, a
   content site, a client who will not pay for tests yet. Record the skip as
   a decision, not an omission. Nothing is registered, and the gate falls back
   to the `implementation_review` requirement that advance seeds when no plan
   and no acceptance criteria exist. Never substitute a fabricated `pytest`,
   and never declare CI or a merge queue for a project with no suite.

A descriptive `verification_profiles.test_command` project-structure entry is
**not** one of these outcomes. It records what the project's tests are for a
human reader; it is not consulted by the gate. Writing it and stopping leaves
the project exactly as unbound as writing nothing.

### Confirm (stop 1 of 2)

The operator confirms or adjusts the whole profile; edits refine the proposal in place. **Nothing mutates before this confirmation.** This confirmation also closes the interview — every remaining unknown is resolved here or recorded as a blocker. Then mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status human-interview=verified \
  --evidence human-interview="execution profile confirmed: {packs}; capabilities {caps}; envs stage+prod; domain {posture}; test setup {surveyed-command|scaffold-suite|explicit-skip}"
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
