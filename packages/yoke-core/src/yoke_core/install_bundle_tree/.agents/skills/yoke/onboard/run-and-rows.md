# /yoke onboard — run init, resume, pacing gates, and checklist rows

Read this once, before step 1, and again whenever a row write or a gate
is due. It carries the run lifecycle and the failure floor; the step
files carry the work.

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

Exactly two stops on a managed-host run. A `deferred|not-needed` branch records step 7's terminal result without presenting the second stop:

1. **Execution-profile confirmation** (step 2) — the whole derived profile is confirmed or adjusted once; nothing mutates before it. The profile always carries a test-setup box; the wizard never asks how a project's tests run, so this skill must.
2. **Infrastructure approval gate** (step 7) — the full apply/deploy preview takes an explicit yes; `[y/N]` defaults No.

Between the profile confirmation and the infrastructure gate, the applying steps (scaffold install, hosting verification, the matching hosted or no-host registration branch, domain record) run straight through unattended. Credential creation is the exception: it always remains user-action plus explicit approval, and the secret values pass only through `--value-stdin` prompts. First-work seeding (step 8) takes one batched confirmation of the proposed item list.

## Checklist rows per step

Checklist rows written per step:

| # | Rows |
|---|---|
| 1 | `repo-survey`, `strategy-setup` |
| 2 | `human-interview` |
| 3 | `scaffold-install`, `documentation-context-setup` |
| 4 | `hosting-setup`, `capability-setup` |
| 5 | `environment-registration`, `project-structure-setup`, `delivery-setup`, `verification-command-binding`, `migration-model-setup` |
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

