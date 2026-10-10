# Refine — Survey, Focus, Policy Re-check

## 3. Survey the actual landscape

Inspect last20 commits in the owning project checkout:
```bash
git -C "<absolute-project-checkout>" log --oneline -20
yoke items list --project "$ITEM_PROJECT" --fields "id,title,status,workflow_id" --limit 1000
yoke items list --project "$ITEM_PROJECT" --status done --fields "id,title,status" --limit 15
yoke items dependency list "$ITEM_REF"
```

Identify actual pipeline stages from relevant pinned definitions. Read only
needed scope/paths for overlapping rows. Verify recent changes for renamed,
removed or changed APIs, already-solved symptoms, obsolete assumptions, reuse,
supersession and directional dependencies. Any physical-file/behavior overlap
needs evidence-backed coordination or ordering, absorption or operator scope
decision. Carry **all** findings into critique; never silently subtract intent.

## 4. Select focus

Item-artifact scope: spec first, then existing UX/design detail.
Generated-task-plan scope: technical_plan/worktree_plan and persisted tasks
must agree. Refine substantive caveats only where that graph policy permits.
When next skill is Blitz, identify its execution document—not a copied body.
Sparse items use the authoritative rendered fallback as input, with additions
routed into structured fields.

## 4b. File Budget and path claims are independent

| Enabled axes | Required action |
|---|---|
| Both | Refined budget and claim coverage must match |
| Claims only | Derive claim paths from spec/execution document; no proxy budget |
| Budget only | Size/conflict evidence; do not register a claim |
| Neither | Skip both artifacts/gates |

Universal350 authored lines still applies. When claims are enabled:
```bash
yoke claims path required-gate PREFIX-N
```

Pass continues. A required_per_task pre-task deferral is not permission to
mint a parent claim; Shepherd materializes persisted task budgets. Existing
generated tasks require a claim repair for each failing task, not a parent
substitute. Block stops advancement until repair.

Register missing exclusive coverage from the applicable touch set, using
--allow-planned for future files; an actual no-repo-surface exception uses
the registered exception flag:
```bash
yoke claims path register --item PREFIX-N --paths <repo-relative-paths> --allow-planned
yoke claims path register --item PREFIX-N --task-num <task-number> --paths <repo-relative-paths>
yoke claims path register --item PREFIX-N --mode exception --exception-reason "<verified-no-surface-reason>"
```

Amend an existing claim rather than replacing its audit history:
```bash
yoke claims path widen --claim-id <claim-id> --add-paths <added-paths> --reason "<verified-scope-expansion>" --item PREFIX-N
yoke claims path amend --claim-id <claim-id> --remove-paths <removed-paths> --reason "<verified-scope-narrowing>" --item PREFIX-N --integration-target <integration-branch>
```

Narrow only after an authorized real scope change; retained coverage must
contain every committed change, with a synced lane head. Follow the exact
snapshot recovery in a refusal; never remove required files to dodge a holder.
With both axes enabled, update budget and claims together.

Classify overlap **before** attesting: use
`yoke claims path coordination-decision-build` and both specs.
Independent disjoint edits use coordination_only; order-dependent edits need
explicit directional activation evidence. Ambiguity escalates. The exact
recipes/release behavior are in
[readiness-repair.md](readiness-repair.md#cross-item-overlap-repair).
No unattested overlap is compatible by assertion alone.

## 5. Critique

Read doctrine, then the full rubric. A required budget cannot stay missing,
vague or unresolved at handoff; update-protocol owns escalation. Skip budget
authoring when disabled, but critique against350. Path-claim block prevents
advance just as DB prose mismatch blocks its separate axis.
