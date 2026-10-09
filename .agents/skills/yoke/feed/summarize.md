# Feed — coherence and summary

## Assess

Coherent requires no reconciliation errors/unresolved conflicts/unencoded
shared-file/contract/deployment overlaps. Remaining stale rows or underdefined
sharpening items are incoherent; set `_frontier_coherent` and specific
`_coherence_issues`.

Record ambiguous preimplementation items (unclear specs/measurable ACs,
conditional dependencies or unencoded overlap) as ref/title/reason.
Derive coding waves from activation blockers, exact integration merge order,
environment waits, actionable decomposition/refinement/cancellation/human
readiness and residual uncertainty from persisted graph facts.

## Complete telemetry and release

Build JSON from structured counts: items_created counts successful creations,
not SKIPPED; preserve mode/decision/edges_added/edges_removed/edges_preserved/
conflicts/frontier_coherent/suppressed.

```sh
yoke events emit --name FeedCompleted --project <project> --kind lifecycle --type feed --source-type skill --severity STATUS --outcome completed --context '<event-context-json>'
```

Telemetry timestamps are disposable; Feed never advances durable
`strategy_checkpoints` review windows.

Release the exclusive FEED process claim before exiting; substitute its acquired
integer `<claim-id>` in both places:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim-id>},
  "intent": "feed_complete",
  "payload": {"claim_id": <claim-id>, "reason": "completed"}
}
```

Surface release errors; still print the operator report.

## Operator report

Always include mode, decision/rationale, exact counts and these sections:

```text
What landed and what it changed:
  landed identities and affected files/contracts/hooks/tests/docs
Work items that need updating:
  ref, actual fields updated/reason, cancellation recommendations with evidence
Decision outcomes:
  area/outcome/rationale
New work items created:
  ref/title/strategy source; skipped entries with reason
Sharpening recommendations:
  ref/actionable missing change/rationale
Dependency rows added/updated/removed:
  added/updated/removed/preserved counts
  exact action: dependent -> blocking [gate/satisfaction] (source), rationale
Coding waves:
  start-now group and groups awaiting activation blockers
Required merge order:
  exact persisted integration rows and reasons
Required environment waits:
  dependent waits for blocker deployment to environment, reason
Readiness callouts:
  each item's missing prerequisite/refinement/decomposition/cancel/human action
Frontier coherence:
  COHERENT/INCOHERENT and specific issues
Residual uncertainty:
  unresolved facts, explicitly
```

When suppressed, mandatory notice:
“Frontier insufficient, new work items suppressed by flag.”
Explain that no-new prevented needed work and rerunning without it permits filing.
Show stale edges/conflicts/ambiguous items/errors only when nonempty, with exact
refs/reasons/counts. Prefer persisted rows to counts alone; avoid vague quantities,
empty decoration and confidence that conceals uncertainty.
