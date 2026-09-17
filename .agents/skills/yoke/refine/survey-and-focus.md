# /yoke refine steps 3–4b — survey, focus, budget and claim re-check

## 3. Contextual Survey

**This step is critical.** Refinement in isolation produces stale, duplicated, or conflicting artifacts. Before critiquing the item, survey the surrounding landscape to ground the critique in reality.

**Recent commits** — What has actually landed recently? The item's assumptions about current codebase state may be outdated.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
git -C "$MAIN_ROOT" log --oneline -20
```

Scan for commits that touch the same files, functions, or subsystems as this item. If recent work has already addressed part of this item's scope, note it — the spec may need descoping or the item may be partially done.

**Active and pipeline work items** — What else is in flight or queued that overlaps?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
yoke db read --format lines "SELECT id, status, title FROM items WHERE status IN ('implementing','reviewing-implementation','reviewed-implementation','polishing-implementation','refining-idea','refined-idea','planning','refining-plan','planned') ORDER BY id DESC"
```

Look for:
- **Overlap** — another work item targeting the same files, functions, or behavior. Flag it in the critique and ensure the spec acknowledges the overlap or deconflicts.
- **Supersession** — a broader work item that subsumes this one. If so, recommend absorbing or cancelling.
- **Dependencies** — a work item that must land first for this item's assumptions to hold, or vice versa.

**Recently done work items** — What just shipped that might affect this item's assumptions?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
yoke db read --format lines "SELECT id, title FROM items WHERE status='done' ORDER BY id DESC LIMIT 15"
```

Check whether recently completed work has:
- Already solved part of this item's problem (descope needed).
- Changed the codebase in ways that invalidate the item's spec, file references, or approach.
- Created new capabilities that this item should leverage instead of building from scratch.

**Staleness check** — Synthesize findings from the three queries above. An item is stale when:
- Its spec references files, functions, or behaviors that have been renamed, removed, or significantly refactored since the spec was written.
- Its problem statement describes a symptom that has already been fixed.
- Its approach assumes codebase state that no longer exists.
- Its scope overlaps with another active or recently-done work item in any way — same files, same behavior, same problem from a different angle. Any overlap must be resolved: descope, absorb, dependency-link, or cancel.

Carry ALL survey findings into the critique in step 5. Staleness and overlap are first-class refinement issues, not optional observations.

## 4. Choose The Refinement Focus

Pick the field(s) to refine based on the current status and whatever structured content actually exists:

- For `REFINE_ARTIFACT_SCOPE=item_artifact`, focus on `spec` first, then
  `design_spec` if the item already has UX or flow detail.
- When `ITEM_NEXT_SKILL=blitz`, also identify the one strategy document that will remain the
  live execution plan. Apply the document-readiness rubric in
  `review-rubric.md`; do not treat the item body as the execution document.
- For `REFINE_ARTIFACT_SCOPE=generated_task_plan`, focus on `technical_plan`
  and `worktree_plan`, and cross-check stored `epic_tasks` against the written
  plan.
- Any status with substantive `shepherd_caveats`: refine `shepherd_caveats` so open questions and deferrals are crisp and actionable.
- If no structured field exists yet, refine the authoritative fallback (`body`) but keep the resulting content ready to migrate into structured fields later.

## 4b. Effective File Budget And Path-Claim Re-Check

Use `ITEM_FILE_BUDGET_POLICY`, `ITEM_PATH_CLAIMS_POLICY`, and their scoped
policies resolved from the immutable pin in step 1:

- Both enabled: confirm path-claim coverage matches the refined File Budget.
- Budget off / claims on: derive claim paths from the item spec or linked
  execution document; do not create a File Budget as a proxy.
- Budget on / claims off: refine the budget for sizing and conflict evidence;
  do not register a claim.
- Both off: skip artifact/gate requirements for both axes.

The universal 350-line authored-file limit remains enforced in every posture.
Run the path-claim gate only when effective path claims are enabled:

```bash
yoke claims path required-gate PREFIX-N
```

Branch on the result:

- **verdict=pass** — no action required; continue to step 5. When both axes
  are enabled and refine narrows the File Budget, record the planned claim
  narrow-down as a critique item; the actual `path-claims narrow` runs in
  step 6.
- **verdict=pass with pre-task deferral** — for a
  `required_per_task` Epic with no generated tasks, do not register or widen an
  item-level claim. Shepherd owns materialization from persisted task budgets.
- **verdict=block** — STOP. Author or amend the claim before proceeding. Three options, picked from the same decision matrix as idea. The canonical product CLI is `yoke claims path register …`; checkout-local db-router registration is operator-debug fallback only.
  1. Register a new exclusive claim (`yoke claims path register --paths …`)
     from the enabled File Budget or, when budget is off, the derived
     execution touch set.
  2. Register with `--allow-planned` when that source names future files.
  3. Register a no-claim exception (`--mode exception --reason "..."`) when refine determines the item legitimately touches no repo surface.

  For `required_per_task` with generated tasks, repair each failing task with
  `yoke claims path register --item PREFIX-N --task-num <N> ...`; an unbound
  parent claim never satisfies this verdict.

  When registration fails due to overlap with a non-terminal claim owned by another item, classify the overlap via `yoke claims path coordination-decision-build` and author either `--gate-point coordination_only` (compatible overlap with no lifecycle gate, default for independent same-file edits) or explicit `--gate-point activation` with directional rationale (order-dependent edits). See [`readiness-repair.md`](readiness-repair.md) `## Cross-item overlap repair`.

When both axes are enabled and refine widens the File Budget mid-pass
(discovers additional files), use `yoke claims path widen --claim-id <id>
--add-paths <added> --reason "<why widening>" --item PREFIX-N` rather than
registering a fresh claim — widen preserves the audit trail in
`path_claim_amendments`. If refine narrows, use the checkout-local
`path-claims narrow` operator-debug/refine disposition; no public narrow
wrapper is registered yet. Prefer the `--keep-paths` form because it names
the paths that stay (`--reason` is required); use `--drop-paths` when the goal
is to remove specific files from a wider claim instead.

The claim re-check is **blocking**: refine MUST NOT advance the item past
`REFINE_ACTIVE_STATUS` while the gate returns `block`. The lifecycle event
gate `GATE_DB_CLAIM_PROSE_MISMATCH` only covers DB-mutation claims; this gate
is the path-claim equivalent and runs alongside it.


Next: read [`doctrine.md`](doctrine.md), then
[`review-rubric.md`](review-rubric.md) and emit the critique.
