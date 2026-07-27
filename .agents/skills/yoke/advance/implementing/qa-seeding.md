# Active — QA Seeding

Seeds QA requirements before implementation begins. Called by the active router as the QA-seeding phase.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`

---

## QA Lifecycle for Non-Conduct Items

When advancing a non-epic item to `implementing`, the implementing agent is responsible for the full QA loop: seed -> implement -> test -> record. This ensures the done-gate has data to check.

### a. Seed QA Requirements (before coding)

Project-default and item-attached plans are the primary source of requirements.
The test-and-record phase materializes their immutable case snapshots for the
`reviewing-implementation` transition before execution. Do not derive a
consolidated requirement from item type, acceptance-criteria prose, or Browser
posture.

When the item's verification contract calls for coverage outside its attached
plans, add only that explicit item-specific requirement:

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

The `--success-policy` field is a human-readable description of what "pass"
means (e.g., "test suite passes with zero failures", "config change verified
in output"). If no plan is attached and the item has no acceptance criteria,
seed at minimum one explicit requirement with
`--qa-kind implementation_review` and
`--success-policy "Implementation matches the item title/description"`.

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
