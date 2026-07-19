---
name: onboard-project
description: Harness-side agentic project adoption after deterministic install; consumes the install report and durable onboarding checklist instead of rediscovering setup.
argument-hint: "--project-root PATH (--run-id RUN | --checklist-view PATH) [--project PROJECT] [--install-report PATH]"
---

# /yoke onboard-project

Adopt an already-installed project into Yoke from a supported harness. This is the slash-command skill for agentic project adoption after deterministic setup, not the product CLI command `yoke onboard project`.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Inputs

Resolve these before doing project adoption work:

- `--project-root PATH` — the target project checkout. Use this as the filesystem scope for repo survey and local rendered views.
- `--run-id RUN` — preferred durable checklist id.
- `--checklist-view PATH` — allowed only as a pointer to the rendered project-local checklist view, normally `.yoke/onboarding/CHECKLIST.md`. Read it to extract the displayed `Run: ...`, then use `yoke onboard checklist --run-id ... --json` as the authoritative read.
- `--project PROJECT` — optional project slug/id for commands that need explicit project context.
- `--install-report PATH` or install report text already present in the handoff/session — the existing `yoke project install` JSON report. Consume it; do not rerun deterministic setup.

If the project checkout or checklist run id cannot be resolved, ask the operator for only the missing value. If the install report is absent, ask for the captured report or its path; do not infer install state by crawling generated files.

## Authority

- Checklist authority is `yoke onboard checklist --run-id {run_id} --json`. Do not treat project-local checklist Markdown as authority.
- Install evidence is the existing `yoke project install` report from handoff or `--install-report`. Use it to understand what setup already wrote, preserved, skipped, or warned about.
- The generated board view is read-only. Do not edit `.yoke/BOARD.md`.
- Do not hand-write project-local runtime, browser, or core implementation files during onboarding. Reusable capability code lands only through the preview-first Pack surfaces below; all other project-adoption writes use their named Yoke CLI surfaces.

## Row Updates

Update checklist rows as each phase progresses. Use the durable run id every time:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status repo-survey=verified \
  --evidence repo-survey="surveyed manifests, docs, CI, runtime shape" \
  --project-root {project_root}
```

Use `verified` for checked facts, `configured` for setup writes applied, and `blocked` with `--blocker ROW=TEXT` when human input or missing access prevents progress. Keep these rows current: `repo-survey`, `human-interview`, `documentation-context-setup`, `strategy-setup`, `project-structure-setup`, `capability-setup`, `delivery-setup`, `verification`, and `lifecycle-readiness`.

## Workflow

### 1. Intake

1. Resolve `project_root`, `run_id`, optional `project`, and the existing install report.
2. Read the durable checklist:

   ```bash
   yoke onboard checklist --run-id {run_id} --json
   ```

3. Confirm the checklist project fields match the checkout and install report. If they conflict, mark the first affected row blocked and stop:

   ```bash
   yoke onboard checklist --run-id {run_id} \
     --row-status repo-survey=blocked \
     --blocker repo-survey="checkout, checklist, and install report identify different projects"
   ```

### 2. Repo Survey

Survey only the target checkout. Prefer `rg --files {project_root}` and focused reads of manifests, README/runbooks, package files, CI definitions, deployment config, test config, and existing `.yoke/` contract docs. Identify:

- Project type, package manager, build/test commands, service entrypoints, and runtime versions.
- Existing docs that should feed strategy, Project Structure, delivery, and QA setup.
- External systems, required secrets, deployment targets, and unknowns.
- Existing generated or rendered Yoke files that should be refreshed through sanctioned surfaces rather than edited directly.

Then mark:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status repo-survey=verified \
  --evidence repo-survey="repo survey complete: {short evidence}"
```

### 3. Human Interview And Blockers

Ask only for unknowns the repo survey and install report cannot answer: product purpose, canonical project name/prefix, deployment environments, owned domains, required third-party credentials, compliance constraints, QA expectations, and first lifecycle target.

For GitHub automation, ask for and record one explicit project mode before any
project or GitHub write:

- `app-binding` — bind the exact repository selected from the machine's GitHub
  App installation access.
- `backlog-only` — keep GitHub automation disabled until an App installation
  can see the repository with the required permissions.

The operator authorizes the machine through `yoke github connect`; project onboarding never asks for, stores, or promotes a GitHub token. An App binding is active only when the selected repository belongs to a non-suspended
installation and that installation has all required repository permissions.
Otherwise preserve the verified binding as pending and keep the project in
`backlog_only`. Administration permission is optional and only unlocks
owner-scoped repository creation and other documented administrative setup.

If answers are complete:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status human-interview=verified \
  --evidence human-interview="operator answered adoption unknowns"
```

If anything blocks setup, mark the specific setup row and `human-interview` blocked with evidence. Do not guess secrets, owners, domains, or deployment settings.

### 4. Apply Sanctioned Setup

Use the existing surfaces; do not patch Yoke DB state through lower-level commands.

Project Structure:

```bash
yoke project-structure patch apply --project {project} --ops-json '{json_ops}'
yoke onboard checklist --run-id {run_id} \
  --row-status project-structure-setup=configured \
  --evidence project-structure-setup="applied Project Structure policy rows"
```

Strategy docs:

```bash
yoke strategy doc list --project {project} --json
yoke strategy doc get MISSION --project {project} --json
yoke strategy doc create {SLUG} --project {project} --content-file {path}
yoke strategy doc replace {SLUG} --project {project} --base-updated-at {timestamp} --content-file {path}
yoke strategy render --project {project} --target-root {project_root}
```

If the adoption edits rendered strategy files locally first, write them back with:

```bash
yoke strategy ingest {SLUG} --project {project} --target-root {project_root}
```

After the corpus is configured and rendered:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status strategy-setup=configured \
  --evidence strategy-setup="strategy docs created/replaced/rendered via Yoke"
```

Documentation/context setup:

Use `yoke packs list --project {project} --json` to inspect reusable capabilities. Preview each relevant Pack against the target checkout before applying it; do not force conflicts or install unrelated Packs. Pack output becomes ordinary project-owned source, customization is expected, and `.yoke/packs.json` records the applied baseline for independent future updates.

If an installed Pack file has moved, preview `yoke packs relink {pack} {project_root} --project {project} --from {old_path} --to {new_path}` and apply the same command with `--apply` only after the mapping is confirmed. Relink updates the receipt path only; it never moves or rewrites project source.

```bash
yoke packs list --project {project} --json
yoke packs get {pack} {project_root} --project {project}
yoke packs get {pack} {project_root} --project {project} --apply
yoke onboard checklist --run-id {run_id} \
  --row-status documentation-context-setup=configured \
  --evidence documentation-context-setup="runbooks/context docs configured through sanctioned surfaces"
```

Capabilities and secrets:

Preview the project/GitHub automation write plan before applying any mutation. The preview must cover project writes plus GitHub labels, issue/PR templates, Actions variables/secrets, branch protection, and environment protection. Record the binding mode, selected repository, installation, permission result, and a redacted preview summary in checklist evidence.

```bash
yoke onboard project {project_root} --slug {project} --name "{project_name}" \
  --github-repo {owner_repo} --default-branch {branch} \
  --public-item-prefix {prefix} --github-adoption {choice} \
  --config {config_path} --dry-run --json
```

Verify the machine App connection and project capabilities. GitHub authority is
the project App binding plus control-plane installation-token minting; it is not
a project capability secret:

```bash
yoke github status --json
yoke projects capability has --project {project} --cap-type aws-admin --json
yoke projects capability-secret set --project {project} --cap-type aws-admin --key access_key_id --value-stdin
yoke projects capability-secret set --project {project} --cap-type aws-admin --key secret_access_key --value-stdin
yoke onboard checklist --run-id {run_id} \
  --row-status capability-setup=configured \
  --evidence capability-setup="GitHub App binding and required capabilities checked; non-GitHub secrets imported by Yoke-owned secret surface"
```

Never print raw secret values. Record redacted evidence only.

Delivery settings:

Use Project Structure rows, strategy docs, installed Pack guidance, and project-owned docs to capture sites, environments, flows, deploy/runbooks, and automation settings. If a required delivery CLI surface is missing, file a field-note before choosing a fallback.

```bash
yoke projects infrastructure list --project {project} --json
yoke project-structure patch apply --project {project} --ops-json '{delivery_json_ops}'
yoke events emit --name ProjectOnboardingDeliveryConfigured \
  --kind lifecycle --type project_onboarding --source-type agent \
  --project {project} --context '{"run_id":"{run_id}"}'
yoke onboard checklist --run-id {run_id} \
  --row-status delivery-setup=configured \
  --evidence delivery-setup="delivery settings captured and event emitted"
```

Use the metadata-only infrastructure inventory to discover exact site and
environment IDs. Read environment configuration only through explicit scalar
leaf projections, for example `yoke projects environment-settings get
--project {project} --environment-id {environment_id} --path
registry.repository --json`; never dump an environment settings document.

QA:

Seed explicit QA requirements for the first project-scoped item only when the project has an item target. For project-level adoption notes, capture QA expectations in Project Structure or strategy docs.

```bash
yoke qa requirement list --item {ITEM} --json
yoke qa requirement add --item {ITEM} --qa-kind ac_verification --qa-phase verification \
  --blocking-mode blocking --requirement-source explicit
yoke qa requirement add-batch --item {ITEM} --stdin
```

### 5. Verification

Reread the checklist and verify configured rows are not merely assumed:

```bash
yoke onboard checklist --run-id {run_id} --json
yoke strategy doc list --project {project} --json
yoke github status --json
yoke events emit --name ProjectOnboardingVerificationCompleted \
  --kind lifecycle --type project_onboarding --source-type agent \
  --project {project} --context '{"run_id":"{run_id}"}'
yoke onboard checklist --run-id {run_id} \
  --row-status verification=verified \
  --evidence verification="checklist, strategy docs, capabilities, and events verified"
```

If lifecycle entry is ready, mark it verified; otherwise mark it blocked or deferred with the missing next action:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status lifecycle-readiness=verified \
  --evidence lifecycle-readiness="first project-scoped lifecycle path is ready"
```

### 6. Handoff

Finish with a concise summary containing:

- project checkout and project slug/id
- checklist run id and open/blocked rows
- install report highlights and warnings consumed
- sanctioned setup surfaces used
- secrets imported, named by capability/key only
- verification evidence
- remaining blockers or deferred work

Do not claim adoption is complete while any required row is `unknown`, `needed`, or `blocked`.
