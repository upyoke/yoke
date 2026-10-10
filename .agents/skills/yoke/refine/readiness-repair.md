# Refine — Readiness Classification and Repair

Run only for item-artifact source entry, and again at final closure.
Read payload verdict/classification, not exit status. Classify **before**
release; recoverable drift keeps the chain and work claim.

## Classifier

`idea_readiness_results.classify_readiness_issues` (reexported by
idea_readiness_repair) classifies issues; unavailable is run-level.

| Class | Evidence and action |
|---|---|
| pass | No issues: continue |
| pure_stale_count | All STALE_LINE_COUNT: registered numeric repair, rerun, keep claim on pass; refusal blocks |
| mixed_stale_count | Only MISSING_FILE_BUDGET, FILE_BUDGET_NOT_IN_CLAIM, CLAIM_NOT_IN_FILE_BUDGET, cross_item_overlap and optional STALE_LINE_COUNT: repair coverage, classify overlap; on residual/refusal continue into refine critique, final rerun still mandatory |
| unrecoverable | Other/mixed nonrecoverable issues: checkpoint, release readiness-check-blocked, exit1 |
| unavailable | Unperformed host checks with retryable:false: no repair/retry here; checkpoint, release readiness-validation-unavailable, report every check/recovery |

A lone missing budget at idea auto-appends the documented UNRESOLVED marker,
not invented paths; Refine resolves its shape before exit. Coverage helper
auto-widens/narrows applicable unambiguous claims. Mixed widen+narrow,
zero/multiple exclusive claims and nonrecoverable mixes return refused_paths,
which remain critique work. Pure stale repair refusal is terminal, not bypassed.

## Helper limits

```bash
yoke readiness check "$ITEM_REF" --json
yoke readiness repair-stale-count --item "$ITEM_REF"
yoke readiness repair-claim-coverage --item "$ITEM_REF"
```

The stale helper rechecks pure classification, reads canonical spec, updates
only numeric counts from live files and refuses absent files, missing/nonnumeric
counts, >=330 (SIBLING_REQUIRED_THRESHOLD) without sibling plan, and missing
or multiply matched path=count substrings. It uses guarded structured writes:
empty/shrinkage/freeze refusal is not bypassed. Rerun verdict/remaining issues
and best-effort IdeaReadinessAutofixApplied record the outcome.
The **work claim stays** held on successful repair.

Mixed recoverable refusal means **continuing into refine** critique;
final readiness still owns closure. Coverage repair preserves amendment history,
reruns readiness and emits
best-effort IdeaReadinessClaimCoverageRepairApplied. Neither helper rewrites
unrelated prose or skips sibling-plan/readiness gates. The stale helper never
adds/removes budget paths or changes claims. Helpers do not author directional
activation edges; that is an evidence-based authoring decision.

## Terminal checkpoint and release

Before readiness-check-blocked release:
```bash
yoke sessions checkpoint --step 1 --action refine --chainable false --outcome blocked --item "$ITEM_REF"
yoke claims work release --item "$ITEM_REF" --reason "readiness-check-blocked"
```

For unavailable, perform the same blocked checkpoint, then release with
readiness-validation-unavailable. Report release errors and exit1, never
swallow them. Each unavailable_checks entry names check, reason
project_checkout_unavailable and actual recovery. Envelope success does not
mean validation passed. Same-host retry cannot change retryable:false;
move to a machine with the registered project checkout using the returned
project-register recovery, not an unsupported hosted checkout installation.

Dependency conditions: choose the blocker's pinned stage, normally
`status:done`, for an item wait including required delivery and closeout.
Choose `fact:merged` for trunk code. Reserve `fact:deployed:<environment-name>`
for a dependent needing the blocker done with persisted delivery attribution
to a registered environment.

## Cross-item overlap repair

The readiness probe emits cross_item_overlap for unresolved physical clusters;
attested coordination_only, directional dependent/blocker evidence or active
operator override satisfies its respective branch. Copy the returned
context.recovery_command, or:
```bash
yoke claims path coordination-decision-build --item PREFIX-N --conflicting-claim <claim-id> --paths <shared-paths>
```

Read both specs/claim states and returned proposals **before** authoring.
Independent disjoint edits use coordination_only with shared-path/subsection
rationale. Directional activation requires the upstream change this candidate
inherits. Ambiguous evidence: release coordination-decision-escalated and
exit1 for operator decision.
```bash
yoke items dependency add <candidate-ref> <conflicting-ref> refine --gate-point coordination_only --rationale "<shared-paths-and-disjoint-subsections>"
yoke items dependency add <candidate-ref> <upstream-ref> refine --gate-point activation --satisfaction fact:merged --rationale "decision=directional. <upstream-change-this-item-inherits>"
```

Choose the blocker's pinned status (normally status:done) for delivery/closeout
wait; fact:merged for trunk code; fact:deployed:ENV only when live environment
proof is needed before dependent completion. Rerun readiness after attestation.
No edge is authored simply because two path strings match.

## Tentative and symlink coverage

Exact likely-but-unconfirmed paths may be tentative, not broad directories.
List them in every enabled surface, and use --tentative-paths as a subset of
registered --paths. They participate in overlap; untouched tentative targets
release without a broken promise. Planned/observed states are not downgraded.
Explicit new registration without that subset upgrades intent; automatic
re-resolution retains sticky tentative state. Verify the amendment result.

Symlink and canonical file form one physical coordination unit. Registration
auto-pairs both; with both axes enabled, readiness advises adding the canonical
path to the budget without blocking. Underlying coverage already spans both.

## Verification

```bash
yoke readiness check PREFIX-N
yoke readiness repair-stale-count --item PREFIX-N
yoke watch pytest --impacted main --bounded
```

Use your project's registered verification command for touched paths,
rather than hardcoding a test-file list. CI uses the committed lane when
configured; commit first. Local checks are only small targeted runs expected
within about one minute, never a slow run justified by dirty work.
