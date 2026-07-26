# Active — QA Seeding

Seeds QA requirements before implementation begins. Called by the active router as the QA-seeding phase.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`

---

## QA Lifecycle for Non-Conduct Items

When advancing a non-epic item to `implementing`, the implementing agent is responsible for the full QA loop: seed -> implement -> test -> record. This ensures the done-gate has data to check.

### a. Seed QA Requirements (before coding)

After reading the item's ACs, seed the AC-derived verification requirement. The verification-entry gate (`implementing → reviewing-implementation`) hard-requires at least one `qa_requirements` row, so every non-epic item needs this before it can advance.

**Primary — auto-create.** Run the registered auto-create surface (function id `qa.requirement.auto_create_for_item`). It creates ONE consolidated `ac_verification` requirement (qa_kind=ac_verification, qa_phase=verification, blocking_mode=blocking, requirement_source=ac_derived) whose `success_policy` lists the pytest target plus every AC. It is idempotent — if an AC-derived `ac_verification` requirement already exists (e.g. seeded by shepherd during `planning_to_plan_drafted`) it returns that row instead of creating a duplicate, so no separate dedup check is needed:

```bash
yoke qa requirement auto-create-for-item --item YOK-{N}
```

The AC-verification requirement is independent of the method cases that prove
browser, command, or machine behavior. A Browser case never suppresses the AC
requirement.

**Fallback — manual seed.** If auto-create reports `not_applicable` because the
workflow does not use project-transition QA, add only the explicit requirement
the item's posture calls for:

```bash
yoke qa requirement add \
  --item YOK-{N} \
  --qa-kind ac_verification \
  --qa-phase verification \
  --blocking-mode blocking \
  --requirement-source ac_derived \
  --success-policy "{brief description of what passing looks like}"
```

The write is item-claim-gated; the advance session already holds the work claim, so it dispatches cleanly. Operator-debug fallback inside a checkout: `python3 -m yoke_core.domain.qa requirement-add --item-id {N} ...` (also the only surface for epic-task / deployment-run-attached requirements).

The `--success-policy` field is a human-readable description of what "pass" means (e.g., "test suite passes with zero failures", "config change verified in output"). If the item has NO acceptance criteria (title-only), seed at minimum one requirement with `--qa-kind implementation_review` and `--success-policy "Implementation matches the item title/description"`.

### Browser case authoring

When the verification contract calls for Browser proof, read
`implementing/browser-seeding.md`. It attaches a reusable plan or authors an
explicit `browser-check` / `browser-inspection` method case. It never derives
requirements from an item classification field.

### Project-default plan cases

Do not inspect project-structure command settings or seed free-form `quick`,
`full`, `e2e`, or `smoke` requirements. Project-owned verification is attached
as QA plan defaults at the workflow transitions where it runs. The transition
router materializes those cases immediately before execution.

This phase seeds only item-specific and AC-derived requirements.
Project-default cases remain immutable plan contracts and are
executed through `yoke qa case run` after materialization.
