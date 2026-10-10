# Onboard — run, pacing and row authority

Read before step 1 and whenever a gate or row write is due.

New projects interview → derive → create; existing repos survey → map →
reconcile the same steps. Survey manifests/docs/CI/runtime directly; no
deterministic detection registry substitutes for that judgment.

Resume the known run; initialize only when this project has none. Record the
returned ID and reuse it for every write:

```bash
yoke onboard checklist --run-id {run_id} --json
yoke onboard checklist init --project {project} --checkout {checkout} --json
```

Reentry evaluates each live skip predicate; it never blindly re-applies.
Requested reconfigure shows the proposed delta and uses the same ordinary
confirmation/approval gate. Every gate leaves a coherent resumable partial state.

## Pacing

Exactly two stops on a managed-host run: whole execution-profile confirmation
(step 2), then full infrastructure preview and explicit yes (step 7);
`[y/N]` defaults No. No-host `deferred|not-needed` records its terminal
step-7 answer without that second stop.

After confirmation, steps 3–6 run unattended. Credential creation always
requires user-action plus explicit approval; values enter terminal
`--value-stdin` prompts only. Step 8 separately takes one batched confirmation
of the item list.

## Rows and failure floor

| Step | Rows |
|---|---|
| 1 | `repo-survey`, `strategy-setup` |
| 2 | `human-interview` |
| 3 | `scaffold-install`, `documentation-context-setup` |
| 4 | `hosting-setup`, `capability-setup` |
| 5 | `environment-registration`, `project-structure-setup`, `delivery-setup`, `verification-command-binding`, `migration-model-setup` |
| 6 | `domain-setup` |
| 7 | `infra-apply-first-deploy` |
| 8 | `work-seeding`, `lifecycle-readiness`, `verification` |

Every step writes its row and echoes what changed/where:
`verified` means checked facts; `configured` means applied setup;
`not-needed` means confirmed exclusion; `deferred` means explicit postponement.

```bash
yoke onboard checklist --run-id {run_id} --row-status {row}=configured --evidence {row}="{what was written and where}"
```

**Failure floor:** missing input/access or a failed operation writes
`blocked` with exact error and recovery, then stops. Completed writes stay in place.
The first unmet skip predicate is the resume point; never undo prior steps.

```bash
yoke onboard checklist --run-id {run_id} --row-status {row}=blocked --blocker {row}="{missing fact or captured failure; exact recovery recipe}"
```
