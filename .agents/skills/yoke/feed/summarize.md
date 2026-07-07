# Summarize

Emit the `FeedCompleted` event and print the operator-facing summary. This is the final stage of `/yoke feed`.

## Inputs (from prior stages)

- **`_mode`**: `"default"` or `"no-new-tickets"` (from argument parsing)
- **`_decision`**: One of `leave_in_sml`, `refresh_only`, `sharpen_frontier`, `materialize_new` (from the Decide stage)
- **`_decision_rationale`**: Human-readable explanation of why this decision was chosen (from the Decide stage)
- **`_decision_outcomes`**: Per-area leave/refresh/sharpen/materialize outcomes (from the Decide stage)
- **`_no_new_tickets_suppressed`**: Boolean -- true when `--no-new-tickets` forced a downgrade from `materialize_new` (from the Decide stage)
- **`_updated_items`**: List of updated or cancellation-recommended frontier items (from the Materialize stage)
- **`_materialized_items`**: List of `{ yok_id, title, sml_source }` for items created (from the Materialize stage, may be empty)
- **`_sharpen_recommendations`**: List of `{ yok_id, title, recommendation }` for items needing refinement (from the Materialize stage, may be empty)
- **`_edge_mutations`**: Exact rows added/updated/removed/preserved during reconciliation (from the Reconcile stage)
- **`_edges_added`**: Count of new feed dependency edges created (from the Reconcile stage)
- **`_edges_updated`**: Count of existing feed edges modified (from the Reconcile stage)
- **`_edges_removed`**: Count of stale feed edges deleted (from the Reconcile stage)
- **`_edges_preserved`**: Count of manual edges left untouched (from the Reconcile stage)
- **`_stale_edges`**: List of stale non-feed edges with cleanup recommendations (from the Reconcile stage)
- **`_conflicts`**: List of feed-vs-manual edge conflicts with resolution notes (from the Reconcile stage)
- **`_reconcile_errors`**: List of errors from reconciliation (from the Reconcile stage, should be empty)
- **`_no_new_tickets`**: Boolean flag (from argument parsing)
- **`_lane`**: Execution lane identity (from argument parsing)
- **`_model`**: Model identifier (from argument parsing)
- **Recent landed change report**: Summary of what recently landed and what it changed (from the Gather stage)

## 5.1 Compute Frontier Coherence

Determine whether the dependency graph is now coherent enough for scheduler, charge, and usher consumers.

The graph is **coherent** when ALL of the following are true:
- `_reconcile_errors` is empty (no errors during reconciliation)
- `_conflicts` is empty or all conflicts have been resolved in favor of manual edges
- No frontier items remain without dependency encoding when they share files, contracts, or deployment surfaces

The graph is **incoherent** when ANY of the following are true:
- `_reconcile_errors` is non-empty
- `_stale_edges` is non-empty (stale edges remain that could mislead consumers)
- `_conflicts` is non-empty and unresolved
- The decision was `sharpen_frontier` but items remain underdefined

Record:
```
_frontier_coherent = true if coherent, false otherwise
_coherence_issues = [<list of specific issues if incoherent>]
```

## 5.2 Identify Ambiguous Items

Scan the frontier for items that remain non-runnable after this feed run. An item is ambiguous when:
- It is in a pre-implementation status (`idea`, `refining-idea`, `refined-idea`, `planning`, `refining-plan`, `planned`) AND
- It has no clear spec or acceptance criteria, OR
- It has conditional language in its dependencies ("if this turns out to..."), OR
- Its scope overlaps with another item without explicit dependency encoding

For each ambiguous item, record:
```
_ambiguous_items.append({
 yok_id: "YOK-N",
 title: "<title>",
 reason: "<specific explanation of why this item is non-runnable>"
})
```

## 5.3 Build Coding Waves And Merge Order

Translate the reconciled dependency graph into an operator-usable execution plan:

- **Coding waves** -- group items by activation blockers so the operator can see what can start now vs what waits for another item to be done/passed
- **Required merge order** -- list every `integration` dependency row that permits parallel coding but constrains merge order
- **Readiness callouts** -- list items that still need decomposition, refinement, cancellation, or human judgment before execution is truthful
- **Residual uncertainty** -- list any open ambiguities that remain after updates and reconciliation

Prefer explicit item IDs and exact dependency rows over prose summaries.

## 5.4 Emit FeedCompleted Event

Build the event context JSON and emit via the registered telemetry surface:

```bash
_items_created=$(echo "$_materialized_items" | grep -c 'yok_id' 2>/dev/null || echo 0)

_event_context="{\"mode\":\"${_mode}\",\"decision\":\"${_decision}\",\"items_created\":${_items_created},\"edges_added\":${_edges_added},\"edges_removed\":${_edges_removed},\"edges_preserved\":${_edges_preserved},\"conflicts\":$(echo "$_conflicts" | grep -c '.' 2>/dev/null || echo 0),\"frontier_coherent\":${_frontier_coherent},\"suppressed\":${_no_new_tickets_suppressed}}"

yoke events emit \
 --name "FeedCompleted" \
 --project "${_project}" \
 --kind lifecycle \
 --type feed \
 --source-type skill \
 --severity STATUS \
 --outcome completed \
 --context "$_event_context"
```

The `created_at` timestamp on this event row records when feed last ran. The post-delivery drift-review model uses `DriftReviewCompleted` and `StrategizeCompleted` as checkpoint anchors rather than `FeedCompleted`.

## 5.4b Release FEED Process Claim

Release the exclusive process work claim acquired at SKILL.md entry. The claim is the only lock this loop holds — releasing it reopens the strategy write window for other sessions.

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "feed_complete",
  "payload": {"claim_id": <claim_id>, "reason": "completed"}
}
```

A release failure surfaces as a response error but does not block the operator summary.

## 5.5 Print Operator Summary

Print a structured summary to stdout. The summary must include ALL of the following sections:

```
===================================================================
FEED COMPLETE
===================================================================

Mode: {_mode}

Decision: {_decision}
 {_decision_rationale}

What landed and what it changed:
 - {recent landed change summary with impacted files/contracts/hooks/tests/docs}

Tickets that need updating: {count}
 {For each item in _updated_items:}
 - {yok_id}: fields updated = {fields_updated}; reason = {reason}
 - {If recommend_cancel:} cancellation recommended -- {cancellation_reason}

Decision outcomes:
 {For each entry in _decision_outcomes:}
 - {area}: {outcome} -- {rationale}

New tickets created: {count}
 {For each item in _materialized_items:}
 - {yok_id}: {title} (source: {sml_source})

Sharpening recommendations: {count}
 {For each item in _sharpen_recommendations:}
 - {yok_id}: {title} -- {recommendation}

Dependency rows added/updated/removed:
 Counts:
 added={_edges_added} updated={_edges_updated} removed={_edges_removed} preserved={_edges_preserved}
 Exact rows:
 {For each entry in _edge_mutations:}
 - {action}: {dependent} -> {blocking} [{gate_point} / {satisfaction}] ({source}) -- {rationale}

Coding waves:
 - Wave 1: {items that can start now in parallel}
 - Wave 2+: {items gated by activation blockers}

Required merge order:
 - {dependent} must merge after {blocking} because {rationale}

{If _stale_edges is non-empty:}
Stale edges detected ({count}):
 {For each stale edge:}
 - {dependent} -> {blocking}: {reason}

{If _conflicts is non-empty:}
Conflicts ({count}):
 {For each conflict:}
 - {dependent} -> {blocking}: {description}

Readiness callouts:
 - {items not yet executable and what they still need}

Frontier coherence: {COHERENT or INCOHERENT}
 {If incoherent, list each issue from _coherence_issues}

{If _ambiguous_items is non-empty:}
Ambiguous items ({count}):
 {For each ambiguous item:}
 - {yok_id}: {title}
 Reason: {reason}

{If _no_new_tickets_suppressed:}
NOTE: Frontier insufficient, new tickets suppressed by flag.
The analysis determined new tickets were needed but --no-new-tickets
prevented materialization. Re-run without --no-new-tickets to create
the missing items.

Residual uncertainty:
 - {anything the run still could not resolve cleanly}

{If _reconcile_errors is non-empty:}
ERRORS ({count}):
 {For each error:}
 - {error description}

===================================================================
```

### Summary Rules

1. **Always report mode** -- even when it is `"default"`, print it explicitly.
2. **Always report the decision and rationale** -- the operator must understand why this outcome was chosen.
3. **Always report exact counts** -- never use vague language like "some" or "several."
4. **Suppression notice is mandatory** -- when `_no_new_tickets_suppressed` is true, the `NOTE:` block MUST appear.
5. **Coherence assessment is mandatory** -- when the graph is stale or incoherent, say so explicitly.
6. **Dependency rows should be exact when available** -- prefer the real persisted rows over summary-only counts.
7. **Readiness callouts must be actionable** -- "not ready" is insufficient without the missing prerequisite or refinement named explicitly.
8. **Residual uncertainty must stay explicit** -- never hide unresolved ambiguity behind a confident summary.
9. **Empty sections are omitted** -- if there are no stale edges, conflicts, ambiguous items, or errors, omit those sections entirely to keep the output clean.

## Context Produced

This phase is terminal -- it produces no context for subsequent phases. The outputs are:
- The `FeedCompleted` event row in the events table
- The printed operator summary on stdout
