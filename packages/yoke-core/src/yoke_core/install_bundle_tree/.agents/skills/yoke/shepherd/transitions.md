# /yoke shepherd steps 3–6 — derive, resume, execute, finalize

## 3. Derive Transitions From The Validated Binding

The supported pinned Shepherd segment yields:
- `refined-idea` -> `refined_idea_to_planning`, `planning_to_plan_drafted`
- `planning` -> `planning_to_plan_drafted`

These transition ids are Shepherd verdict keys for this skill contract.
They are not a global item progression. The next skill at
`_shepherd_through_stage` comes from the pinned definition.

## 4. Resume Logic

Before executing transitions, read prior verdict history:

```bash
_completed=$(yoke db read --format lines "SELECT transition FROM shepherd_verdicts WHERE item='PREFIX-$_num' AND (verdict='READY' OR verdict='CAVEATS' OR verdict='SKIPPED') ORDER BY id")
_blocked=$(yoke db read --format lines "SELECT transition FROM shepherd_verdicts WHERE item='PREFIX-$_num' AND verdict='BLOCKED' ORDER BY id")
```

Rules:
- READY / CAVEATS / SKIPPED -> skip the transition
- BLOCKED -> report and stop
- NOT_READY with attempts remaining -> resume at next attempt
- Otherwise -> execute from attempt 1

If all transitions are already complete, advance the item to
`_shepherd_through_stage` and finish.

## 5. Execute Each Transition

For each remaining transition:

1. Set `_scholar_context=""` (Scholar is still a stub).
2. Gather prior caveats from earlier `CAVEATS` verdicts.
3. Route to the correct transition file:
 - `refined_idea_to_planning` -> [design-and-plan.md](design-and-plan.md)
 - `planning_to_plan_drafted` -> [planning-to-planned-gates.md](planning-to-planned-gates.md), then [boss-verdict.md](boss-verdict.md)
4. After any worker completes, always run [boss-verdict.md](boss-verdict.md) for the review, parsing, persistence, reflection, and retry/result logic.

## 6. Finalize And Report

After each verdict and after the full pipeline completes, read and follow [finalize.md](finalize.md).

That phase owns:
- Shepherd Log rendering and guarded writes
- Transition re-anchoring and auto-continuation
- Progress commits
- Final reporting
- Error handling and DB operations reference
