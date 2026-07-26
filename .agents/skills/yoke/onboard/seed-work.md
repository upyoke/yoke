# Onboard Step 8: Seed The First Work

Turn CURRENT-PLAN into the first backlog items, verify the whole checklist, and hand off to the build loop. The plan, not the deploy, is the input — a deferred or blocked deploy does not block seeding.

- **Entry:** CURRENT-PLAN exists with accepted content.
- **Skip:** this run already recorded seeded items on its `work-seeding` row → report them and skip.
- **Rows:** `work-seeding`, `lifecycle-readiness`, `verification`.

## 1. Derive The Proposed Item List

Read CURRENT-PLAN (`yoke strategy doc get CURRENT-PLAN --project {project}`) and derive a short list of concrete, independently workable items — the plan's near-term outcomes, one item each, titles ≤100 characters. These are `/yoke idea` intakes filed through the registered create surface; follow the idea intake conventions:

- Resolve the deployment flow **before** proposing: `yoke project-structure deploy-defaults get --project {project}` prints the project default (set by the flow declaration in step 5 of this skill); empty output means no flow — omit the flag, and never pass the literal string `none`.
- Infer each item's priority from the plan's language (urgent/broken/blocking → high; nice-to-have/future → low; else medium). Never ask about priority.
- In an existing repo, run the duplicate advisory first: scan the board view and `yoke items search "{keywords}" --project {project}` for overlapping open items; drop or merge duplicates from the proposal.

## 2. Confirm Once (batched)

Present the full proposed list — titles, priorities, flow — in one block and take one confirmation for the whole batch. Edits refine the list in place; do not re-confirm per item.

## 3. File Serially

After the single confirmation, create the items one at a time through the registered create surface. Run each command **bare** — no output wrapping — and read the printed YOK-N from the adapter output before filing the next:

```bash
yoke items create "{title}" issue --entry-surface harness_skill --project {project} --deployment-flow {flow_id} --priority {priority}
```

When no flow applies, omit `--deployment-flow`:

```bash
yoke items create "{title}" issue --entry-surface harness_skill --project {project} --priority {priority}
```

Every seeded item enters at `idea` status; `/yoke refine` owns its spec body next — do not assemble bodies, claims, or dependencies here through lower-level surfaces. Echo each created id with the CURRENT-PLAN outcome it came from.

When the plan names explicit QA expectations for the first item, attach them through the QA requirement surface:

```bash
yoke qa requirement add --item {ITEM} --qa-kind ac_verification --qa-phase verification \
  --blocking-mode blocking --requirement-source explicit
```

Mark the row with the created ids as evidence:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status work-seeding=configured \
  --evidence work-seeding="seeded from CURRENT-PLAN: {YOK ids with titles}"
```

**Failure floor:** a rejected create → record `work-seeding=blocked` with the failing title and adapter error; items already created stay and are listed in the blocker text so the retry proposes only the remainder.

## 4. Verify The Whole Checklist

Reread the checklist and confirm configured rows are real, not assumed:

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

With seeded items in the backlog, lifecycle entry is ready:

```bash
yoke onboard checklist --run-id {run_id} \
  --row-status lifecycle-readiness=verified \
  --evidence lifecycle-readiness="first project-scoped items exist: {YOK ids}"
```

If any required row is still `unknown`, `needed`, or `blocked`, mark `lifecycle-readiness=blocked` naming those rows instead — never claim completion over open rows.

## 5. Hand Off

Finish with the summary the router's Handoff section defines: project, run id, rows, docs, Packs, capabilities (redacted), environments, deploy URL plus smoke result or the explicit deferral, seeded ids, remaining blockers. The session ends with queued work, not a finished configuration screen: point the operator at `/yoke do` to start the build loop — the loop itself is outside this skill.
