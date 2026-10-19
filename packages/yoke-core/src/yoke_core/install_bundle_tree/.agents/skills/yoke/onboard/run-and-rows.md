# Onboard — run, pacing and row authority

Read before step 1 and whenever a gate or row write is due.

New projects interview → derive → create; existing repos survey → map →
reconcile the same steps. Survey manifests/docs/CI/runtime directly; no
deterministic detection registry substitutes for that judgment.

Resume the known run; initialize only when this project has none. Record the
returned ID and reuse it for every write:

```bash
yoke onboard checklist get --project {project} --run-id {run_id} --json
yoke onboard checklist init --project {project} --checkout {checkout} --json
```

Reentry evaluates each live skip predicate; it never blindly re-applies.
Omit --run-id to resolve only this project's saved run. A foreign run refuses
before a write. Read `run.execution_profile`, `profile_changed` and
`run.setup_readiness` and `run.next_action`; follow the returned command and
home. Shared decisions survive, while machine rows describe the
requesting machine. Missing local checks never inherit another machine's proof.
Requested reconfigure shows the proposed delta and uses the same ordinary
confirmation/approval gate. Every gate leaves a coherent resumable partial state.

## Pacing

Step 1 sends one message confirming what to scan, then walks decisions one
at a time. Configuration then follows the first work only: a step it does
not need writes its rows `deferred` with evidence naming that work and asks
nothing. Optional environments, test machines, QA plans, governed
migrations, previews, test registration, Doctor and architecture setup wait
until selected work needs them; item QA can use local tests or review.

At most two more stops: confirmation of the profile choices the first work
needs (step 2), and the infrastructure preview with an explicit yes only when
it deploys to managed infrastructure (step 7); `[y/N]` defaults No.
After confirmation, the needed steps among 3–6 run unattended. Credential
creation always requires user-action plus explicit approval; values enter
terminal `--value-stdin` prompts only. Step 8 asks nothing: steering files the work.

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
| 8 | `work-seeding`, `verification`; `lifecycle-readiness` is read live |

Every step writes its row and echoes what changed/where:
`verified` means checked facts; `configured` means applied setup;
`not-needed` means confirmed exclusion; `deferred` means explicit postponement.
`unknown` means unexamined or unavailable evidence. `saved_status` and
`saved_evidence` retain the choice when current settings show a different fact.
Optional unknown rows do not require another whole-profile interview.

```bash
yoke onboard checklist --run-id {run_id} --row-status {row}=configured --evidence {row}="{what was written and where}"
```

**Failure floor:** missing input/access or a failed operation writes
`blocked` with exact error and recovery, then stops. Completed writes stay in place.
The first unmet skip predicate is the resume point; never undo prior steps.

```bash
yoke onboard checklist --run-id {run_id} --row-status {row}=blocked --blocker {row}="{missing fact or captured failure; exact recovery recipe}"
```
