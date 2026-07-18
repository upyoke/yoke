# Materialize

Execute the decision from the Decide stage by updating stale frontier items, then creating new backlog items or recording sharpening recommendations. This is the only feed stage that mutates backlog items directly.

## Skip Conditions

Skip this phase entirely and produce empty outputs if ALL of these are true:

- `_items_to_update` is empty
- `_decision` is `leave_in_sml` or `refresh_only`
- `_items_to_materialize` is empty AND `_items_to_sharpen` is empty

When skipping, produce:
```
_updated_items = []
_materialized_items = []
_sharpen_recommendations = []
```

Then proceed directly to the Reconcile stage.

## Branch A: Update Stale Frontier Items

For each item in `_items_to_update`, update the affected structured fields before creating any new work.

### 3A.1 Write Matching Structured Fields

For each update entry, dispatch the
`items.structured_field.replace` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md))
with `target = {kind: "item", item_id: <id>}` and
`payload = {field: "<spec|design_spec|technical_plan|worktree_plan>",
content: "<updated field content>", source: "feed"}`.
Operator/debug adapter:
`printf '%s\n' "<updated field content>" | yoke items structured-field replace YOK-{id} --field <field> --source feed --stdin`
(`items structured-field replace` dispatches through
`items.structured_field.replace`).

Rules:
- Prefer the matching structured field (`spec`, `design_spec`,
  `technical_plan`, `worktree_plan`) — `body` is a virtual rendered
  projection and not directly writable.
- If acceptance criteria changed, fold that change into the appropriate
  structured field instead of leaving it as a note elsewhere.
- If scope shifted because landed work subsumed or invalidated part of
  the ticket, state that explicitly in the updated field content.

### 3A.2 Cancellation Recommendations

If an item is no longer needed because landed work absorbed its scope:
- do NOT auto-cancel it inside feed
- record a clear cancellation recommendation with the absorbed-by evidence
- only skip field writes when cancellation is the truthful next action

### 3A.3 Verify And Record

After each update:
- re-read the updated field with `items get` to confirm the write landed
- record the result:

```
_updated_items.append({
 yok_id: "YOK-N",
 title: "<title>",
 fields_updated: ["spec", "technical_plan"],
 reason: "<what landed and why this ticket changed>",
 recommend_cancel: true|false,
 cancellation_reason: "<why>" # only when applicable
})
```

## Branch B: Materialize New Items (`_decision = "materialize_new"`)

For each item in `_items_to_materialize`, execute the following steps in order.

### 3A.1 Dedup Check

Before creating any item, search the existing backlog for potential duplicates:

```bash
yoke db read --format lines "SELECT id, title, status FROM items WHERE project_id = ${_project_id} AND title LIKE '%keyword%' AND status NOT IN ('done','cancelled')"
```

Replace `%keyword%` with 2-3 distinctive words from the proposed title. Check multiple keyword variants to cast a reasonable net.

**If a likely duplicate exists** (same scope, overlapping intent, non-terminal status):
- Do NOT create the item
- Record it as skipped:
 ```
 { yok_id: "SKIPPED", title: "<proposed title>", sml_source: "<source>",
 skip_reason: "Duplicate of YOK-N: <existing title>" }
 ```
- Continue to the next item

**If no duplicate found**, proceed to creation.

### 3A.2 Create via `/yoke idea`

Feed MUST create items through the existing `/yoke idea` pipeline to preserve dedup search, GitHub sync, body generation, and AC normalization. For each item:

Invoke `/yoke idea` inline with the item title. When the idea skill prompts for body context, provide:

1. **Strategic context** from `body_context` in the materialization spec
2. **Strategic Provenance** section (mandatory):
 ```markdown
 ## Strategic Provenance
 - **SML Source:** {sml_source} (e.g., "MASTER-PLAN.md, deployment frontier")
 - **Materialized by:** /yoke feed
 - **Rationale:** {rationale from decide phase}
 ```
3. **Pull-forward justification**: Why this item is ready to be materialized now (from the decide phase rationale)

The `/yoke idea` pipeline handles:
- Title validation (<=100 chars)
- Metadata inference (project, type, priority)
- Duplicate detection (secondary check beyond our 3A.1 check)
- GitHub issue creation and sync
- Body generation with AC normalization

### 3A.3 Record Created Item

After each successful creation, record the result:

```
_materialized_items.append({
 yok_id: "YOK-N", // the ID assigned by idea pipeline
 title: "<item title>",
 sml_source: "<which SML file/section this came from>"
})
```

If the idea pipeline rejects the item (e.g., detected as duplicate during its own dedup), record as skipped with the rejection reason.

### 3A.4 Pacing

Create items one at a time, not in batch. After each creation:
- Verify the item exists in the backlog
- Confirm the strategic provenance section is in the body
- Then proceed to the next item

Prefer fewer, sharper tickets over many vague ones. If the decide phase produced more than 5 items to materialize, pause after the first 3 and reassess whether the remaining items are truly ready for materialization or should stay in the SML.

## Branch C: Sharpen Frontier (`_decision = "sharpen_frontier"`)

For each item in `_items_to_sharpen`, record a specific recommendation. This branch does NOT invoke `/yoke refine` directly -- it produces structured recommendations for the operator to act on.

### 3B.1 Build Recommendations

For each item in `_items_to_sharpen`:

```
_sharpen_recommendations.append({
 item_id: "YOK-N",
 action: "<split|refine|add_spec|add_ac>", // from decide phase
 recommendation: "<specific, actionable description of what needs to change>",
 rationale: "<why this item needs sharpening before new work is added>"
})
```

The recommendation must be specific enough that an operator can act on it without re-analyzing the SML:
- For `split`: Identify the distinct scopes and suggest specific sub-item titles
- For `refine`: Identify what is vague or conditional and what concrete information is needed
- For `add_spec`: Note that the item lacks a spec and describe what the spec should cover
- For `add_ac`: Note that acceptance criteria are missing or unmeasurable and suggest concrete ACs

### 3B.2 No Direct Mutations

This branch does NOT:
- Create new items when `_no_new_tickets` suppressed splitting/materialization
- Create new items for split recommendations unless the operator is in full feed mode and the decision explicitly calls for that work
- Modify existing items
- Invoke `/yoke refine` or `/yoke shepherd`

It only produces `_sharpen_recommendations` for the summary phase to present to the operator.

## Context Produced

After this phase, the following outputs are available for subsequent phases:

- **`_updated_items`**: List of updated or cancellation-recommended frontier items with fields changed and reasons
- **`_materialized_items`**: List of `{ yok_id, title, sml_source }` for each created item (may include SKIPPED entries with `skip_reason`)
- **`_sharpen_recommendations`**: List of `{ item_id, action, recommendation, rationale }` for each item needing sharpening
