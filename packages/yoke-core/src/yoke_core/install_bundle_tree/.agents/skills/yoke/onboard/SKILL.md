---
name: onboard
description: "Make a wired project execution-ready — strategy docs, execution profile, scaffold and infra Packs, hosting, environments, a gated first deploy, and seeded first work."
argument-hint: "[--project P] [--run-id RUN]"
---

# /yoke onboard

Make an already-wired project **execution-ready** from a supported harness. The terminal wizard (`yoke onboard`) owns wire-up — machine profile, account, GitHub, project binding, review. This skill starts from strategy and derives everything else: the strategy-doc corpus, one confirmed execution profile, scaffold and infra Packs, hosting verification, environment/site/flow registration, the domain record, a gated infrastructure apply plus first deploy, and the first seeded work items.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--project P` — project slug. Default: the checkout's mapped project (`yoke projects checkout-context --field slug`).
- `--run-id RUN` — durable onboarding checklist run to resume. When omitted, initialize a new run (see Run Init And Resume below).

## Boundaries

- **Assume the wizard's output; never re-create it.** If the machine, account, GitHub connection, or project binding is missing, stop and point the operator at the `yoke onboard` terminal wizard. This skill never reimplements wire-up.
- **Harness connection is upstream and detect-only.** The skill runs inside an already-connected harness. Detect and link harnesses; never install one for the user.
- **The web views and steers; it never invokes.** The workbench Overview renders this checklist's rows and offers this command as text for the operator to run. No web button runs this skill.
- **Checklist authority** is `yoke onboard checklist --run-id {run_id} --json`. The rendered project-local checklist view is read-only display; never treat it as authority and never edit it.
- **Sanctioned surfaces only.** Every mutation goes through registered `yoke <subcommand>` adapters / function ids — no raw DB writes, no ad hoc shell choreography. Do not hand-write project runtime, browser, or core implementation files; reusable capability code lands only through the preview-first Pack surfaces.
- **Secrets never through the chat.** Credential values go only into terminal `--value-stdin` prompts; the conversation carries redacted evidence only (identity checks, key IDs). Never print raw secret values.
- **Ask only for unknowns.** Anything derivable from strategy, the repo, or recorded settings is proposed, not asked.
- **Echo evidence after every write.** Each completed step reports what was written and where (docs written, Pack version installed, environments registered, deploy URL plus smoke result).

## Two Modes, Same Steps

- **New project** fills the steps from scratch: interview → derive → create.
- **Existing repo** fits current artifacts into the same steps: survey → map → reconcile. The repo survey is agent-driven — read manifests, docs, CI, and runtime shape directly. There is no deterministic detection registry; your own survey is the first pass.

## Run Init And Resume

Resume when a run id is known (authoritative read):

```bash
yoke onboard checklist --run-id {run_id} --json
```

Initialize a standalone run when no run id exists for this project (the command mints and returns the `run_id`; record it and reuse it for every row write in this session):

```bash
yoke onboard checklist init --project {project} --checkout {checkout} --json
```

A re-run walks the same steps, detects each already-satisfied step through its skip predicate, and skips it by default — it never blindly re-applies. On request, any step can be **reconfigured**: re-propose the step's writes, show the delta against current state, and apply the delta behind the same confirmation or approval gate the step normally uses. Every phase gate leaves a coherent partial state; the operator can stop at any gate and resume later.

## Pacing And Gates

Exactly two stops:

1. **Execution-profile confirmation** (step 2) — the whole derived profile is confirmed or adjusted once; nothing mutates before it.
2. **Infrastructure approval gate** (step 7) — the full apply/deploy preview takes an explicit yes; `[y/N]` defaults No.

Between the profile confirmation and the infrastructure gate, the applying steps (scaffold install, hosting verification, environment/site/flow registration, domain record) run straight through unattended. Credential creation is the exception: it always remains user-action plus explicit approval, and the secret values pass only through `--value-stdin` prompts. First-work seeding (step 8) takes one batched confirmation of the proposed item list.

## Step Map

Execute the steps in order. Read each sub-file when its step is next; each file carries the full procedure, recipes, and checklist row writes for its steps.

| # | Step | File | Entry | Skip |
|---|---|---|---|---|
| 1 | Strategy conversation | [strategy-conversation.md](strategy-conversation.md) | Wire-up verified; checklist run active | All five docs present with accepted, non-placeholder content |
| 2 | Derive the execution profile | [profile-and-scaffold.md](profile-and-scaffold.md) | Strategy docs accepted | Only when steps 3–8 all already satisfy their skip predicates (nothing left to apply); otherwise re-derive and re-confirm — the profile is never persisted |
| 3 | Install the scaffold Pack | [profile-and-scaffold.md](profile-and-scaffold.md) | Confirmed profile includes a scaffold Pack (an existing app maps instead of installing) | `.yoke/packs.json` receipt already records the Pack |
| 4 | Hosting capability | [hosting-and-environments.md](hosting-and-environments.md) | Profile requires hosting | `aws-admin` capability present AND live identity probe passes |
| 5 | Infra Packs + environments/sites/flow | [hosting-and-environments.md](hosting-and-environments.md) | Scaffold present (installed or mapped); hosting verified or explicitly deferred | Registrations already match the profile; recorded Packs skip individually |
| 6 | Domain | [domain-and-deploy.md](domain-and-deploy.md) | Environments registered | Domain posture already recorded |
| 7 | Gated infra apply + first deploy | [domain-and-deploy.md](domain-and-deploy.md) | Every earlier step satisfied | Infra applied and the deploy live and healthy |
| 8 | Seed the first work | [seed-work.md](seed-work.md) | CURRENT-PLAN exists (a deferred deploy does not block seeding) | This run already recorded seeded items on its checklist row |

Checklist rows written per step:

| # | Rows |
|---|---|
| 1 | `repo-survey`, `strategy-setup` |
| 2 | `human-interview` |
| 3 | `scaffold-install`, `documentation-context-setup` |
| 4 | `hosting-setup`, `capability-setup` |
| 5 | `environment-registration`, `project-structure-setup`, `delivery-setup` |
| 6 | `domain-setup` |
| 7 | `infra-apply-first-deploy` |
| 8 | `work-seeding`, `lifecycle-readiness`, `verification` |

## Row Updates And The Failure Floor

Every step ends with its checklist row write, using the durable run id:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status {row}=configured \
  --evidence {row}="{short evidence: what was written and where}"
```

Statuses: `verified` for checked facts, `configured` for setup writes applied, `not-needed` when the confirmed profile excludes the step, `deferred` for an explicit operator skip, and `blocked` with `--blocker {row}=TEXT` when human input or missing access prevents progress.

**Failure floor:** a step that fails records `blocked` plus the blocker text on its row and stops there. Completed writes stay in place — never roll back earlier steps. The blocked row is the resume point: the next run resumes at the first step whose skip predicate does not hold.

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status {row}=blocked \
  --blocker {row}="{what is missing and the exact recovery recipe}"
```

## Handoff

After step 8, finish with a concise summary: project slug and checkout, checklist run id with open/blocked rows, strategy docs written, Packs installed with versions, capabilities verified (redacted), environments and flows registered, deploy URL plus smoke result (or the explicit deferral), seeded item ids, and remaining blockers. Do not claim onboarding is complete while any required row is `unknown`, `needed`, or `blocked`. Point the operator at `/yoke do` to start the build loop — the loop itself is outside this skill.
