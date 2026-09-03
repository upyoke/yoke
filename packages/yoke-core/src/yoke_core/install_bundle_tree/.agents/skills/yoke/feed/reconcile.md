# Reconcile

Reconcile the generated dependency graph for each frontier item. This phase writes `source='feed'` dependency rows, preserves operator-authored rows, detects stale edges, and surfaces conflicts.

## Inputs (from prior phases)

- **`_edges_to_generate`**: List of edge specs from the decide phase, each with `dependent`, `blocking`, `gate_point`, `satisfaction`, `rationale`, `evidence_json`
- **`_materialized_items`**: List of newly created items from the materialize phase (may be empty)
- **Frontier items**: All non-terminal items from the gather phase
- **Existing dependency graph**: All dependency edges queried during gather

## 4.1 Group Edges by Dependent Item

Group `_edges_to_generate` by `dependent` item. Reconciliation operates per dependent item to keep the atomic scope manageable.

```
_edges_by_dependent = {}
for edge in _edges_to_generate:
 _edges_by_dependent[edge.dependent].append(edge)
```

## 4.2 Reconcile Per Dependent Item

For each dependent item in `_edges_by_dependent`, use `yoke items dependency add` for individual edge creation with full evidence metadata. The strategy is:

1. **Remove stale feed edges** for this dependent item that are NOT in the new edge set
2. **Add or update feed edges** that ARE in the new edge set
3. **Never touch non-feed edges** (source is not `'feed'`)

### Use `yoke items dependency add` individually

When evidence metadata matters (it always does for feed), use the registered dependency edge writer for each edge individually. First remove stale feed edges, then add new ones:

```bash
# Step 1: Query existing feed edges for this dependent item
_existing=$(yoke db read --format lines "SELECT blocking_item_id, gate_point FROM item_dependencies WHERE dependent_item_id=N AND source='feed'")

# Step 2: For each existing feed edge NOT in the new edge set, remove it
yoke items dependency remove PREFIX-N PREFIX-OLD_BLOCKER

# Step 3: For each new edge, add it with full metadata
yoke items dependency add PREFIX-N PREFIX-M feed \
 --gate-point activation \
 --satisfaction "status:done" \
 --rationale "Shared schema surface: both items modify item_dependencies table" \
 --evidence '{"shared_files":["<path/to/shared/file>"],"blocker_class":"coding_order","constraint_type":"schema"}'
```

Use this registered path for all feed reconciliation so every generated edge carries structured `evidence_json`.

### Gate/Satisfaction Selection

Apply these rules when encoding each edge:

| Blocker class | gate_point | satisfaction | When to use |
|---|---|---|---|
| Coding-order | `activation` | `status:done` | PREFIX-N cannot start until PREFIX-M is done |
| Validation-before-start | `activation` | `status:implemented` | PREFIX-N cannot start until PREFIX-M reaches implemented status |
| Merge-order | `integration` | `fact:merged` | Parallel coding OK but must merge in order |
| Runtime deployment | chosen consumption gate | `fact:deployed:<environment-name>` | The dependent needs the blocker running in that registered environment |
| Closeout | `closure` | `status:done` | PREFIX-N cannot close until PREFIX-M is done |

Use `fact:merged` when trunk contains everything the dependent consumes.
Use the deployed fact for stage/prod QA, an installed environment build, a
live API, or a cross-project consumer that cannot proceed at merge time.

### Deduplication

Before adding an edge, check whether an equivalent edge already exists from any source:

```bash
_existing_edge=$(yoke db read --format lines "SELECT source, gate_point FROM item_dependencies WHERE dependent_item_id=N AND blocking_item_id=M")
```

- If an operator/shepherd/idea edge already encodes the same relation (same dependent, blocking, and compatible gate_point), do NOT create a duplicate feed row. Record this as a preserved manual edge.
- If a feed edge exists with different gate_point or satisfaction, update it via the registered dependency update surface:

```bash
yoke items dependency update PREFIX-N PREFIX-M \
 --match-gate-point activation \
 --gate-point integration \
 --satisfaction "fact:merged" \
 --rationale "Updated: parallel coding now safe, merge order still matters"
```

### Tracking Reconciliation Results

Track four counters per dependent item:

```
_edges_added = 0 # New feed edges created
_edges_updated = 0 # Existing feed edges modified
_edges_removed = 0 # Stale feed edges deleted
_edges_preserved = 0 # Manual edges left untouched (operator/shepherd/idea)
```

Also track exact edge mutations for the final report:

```
_edge_mutations.append({
 action: "added|updated|removed|preserved",
 dependent: "PREFIX-N",
 blocking: "PREFIX-M",
 gate_point: "activation|integration|closure",
 satisfaction: "status:done|status:implemented|fact:merged|fact:deployed:<environment-name>",
 source: "feed|operator|idea|shepherd|conduct",
 rationale: "<why this row exists or changed>"
})
```

## 4.3 Detect Stale Non-Feed Edges

After reconciling feed edges, scan all non-feed dependency edges for staleness. An edge is stale when:

1. **Blocking item is cancelled with resolution_ref.** The blocking item has `status='cancelled'` and its body or resolution indicates the scope was absorbed or abandoned.

2. **Blocking item scope absorbed into dependent.** The blocking item's scope has been merged into the dependent item (e.g., items were consolidated during shepherd).

Query for stale candidates:

```bash
# Find non-feed edges where the blocker is cancelled
yoke db read --format lines "SELECT d.dependent_item_id, d.blocking_item_id, d.source, d.gate_point, d.rationale, i.status, i.title FROM item_dependencies d JOIN items i ON i.id = d.blocking_item_id WHERE d.source <> 'feed' AND i.status = 'cancelled'"
```

For each stale edge found:

- Do NOT remove it automatically (it is operator-authored)
- Record it as a stale edge recommendation:

```
_stale_edges.append({
 dependent: "PREFIX-N",
 blocking: "PREFIX-M",
 source: "<original source>",
 gate_point: "<gate>",
 reason: "Blocking item PREFIX-M is cancelled (title: ...)",
 recommendation: "Remove edge or update to reference successor item"
})
```

Also check for edges where the blocker is `done` but the edge gate has already been satisfied:

```bash
# Find edges where satisfaction condition is already met
yoke db read --format lines "SELECT d.dependent_item_id, d.blocking_item_id, d.gate_point, d.satisfaction, d.source, i.status FROM item_dependencies d JOIN items i ON i.id = d.blocking_item_id WHERE i.status = 'done' AND d.satisfaction = 'status:done'"
```

These satisfied edges are not stale per se (they are correctly resolved), but edges where `satisfaction='status:implemented'` and the blocker is already `done` may warrant review if the dependency was intended to enforce an earlier implementation milestone.

## 4.4 Detect Conflicts Between Feed and Manual Edges

When a feed edge and a manual edge both exist for the same dependent-blocking pair but with different gate_points:

- Preserve the manual edge
- Do NOT create the feed edge
- Record the conflict:

```
_conflicts.append({
 dependent: "PREFIX-N",
 blocking: "PREFIX-M",
 manual_edge: { source: "operator", gate_point: "activation", satisfaction: "status:done" },
 feed_edge: { gate_point: "integration", satisfaction: "fact:merged" },
 resolution: "Manual edge preserved; feed inference differs"
})
```

## 4.5 Idempotency Verification

After completing all reconciliation for all dependent items, verify idempotency by checking that:

1. Every edge in `_edges_to_generate` either exists in the DB or was skipped due to a manual edge conflict
2. No orphaned `source='feed'` edges remain for items that were in scope but had no edges generated

```bash
# For each frontier item that was in scope:
yoke db read --format lines "SELECT COUNT(*) FROM item_dependencies WHERE dependent_item_id=N AND source='feed'"
```

Compare the count against expected edges. If mismatched, log the discrepancy but do not retry (the next feed run will reconcile).

## Context Produced

After this phase, the following outputs are available for the summarize phase:

- **`_edges_added`**: Total count of new feed dependency edges created
- **`_edges_updated`**: Total count of existing feed edges modified
- **`_edges_removed`**: Total count of stale feed edges deleted
- **`_edges_preserved`**: Total count of manual edges left untouched
- **`_edge_mutations`**: Exact dependency rows added/updated/removed/preserved for reporting
- **`_stale_edges`**: List of stale non-feed edges with recommendations for cleanup
- **`_conflicts`**: List of feed-vs-manual edge conflicts with resolution notes
- **`_reconcile_errors`**: List of any errors encountered during reconciliation (should be empty on success)
