# /yoke refine — Blitz Execution Document Handoff

Run this path only when `ITEM_NEXT_SKILL=blitz`. It runs after item-artifact
writes have been verified and before the final
`REFINE_ACTIVE_STATUS -> REFINE_TARGET_STATUS` transition.

## Registered operation authority

Use these registered function ids as the authority. The commands are their
CLI adapters:

| Function id | Target and payload | CLI adapter |
|---|---|---|
| `strategy.doc.list` | Project target; empty payload | `yoke strategy doc list --project PROJECT --json` |
| `strategy.doc.get` | Project target; `slug` | `yoke strategy doc get SLUG --project PROJECT --json` |
| `strategy.execution.get` | Blitz item target; empty payload | `yoke strategy execution get ITEM --project PROJECT --json` |
| `strategy.execution.link` | Blitz item target; `slug` | `yoke strategy execution link ITEM --slug SLUG --project PROJECT --json` |

The link is item metadata. It does not acquire the item-owned document claim.
`/yoke blitz` acquires that claim atomically at activation through the
`doc_claim_activation` lifecycle gate.

## 1. Resolve the item project and any existing link

Use the item project resolved in the main Refine lookup as `ITEM_PROJECT`.
Read the current execution projection first:

```text
yoke strategy execution get "PREFIX-$ITEM_NUM" \
  --project "$ITEM_PROJECT" --json
```

On re-entry:

- If `execution.execution_document.slug` already names the intended
  document, keep it and continue to verification. Do not issue a no-op link.
- If it names a different document, stop at `refining-idea` and surface the
  conflict. Never silently replace a prior Refine decision.
- If `execution.execution_document` is null, continue to selection.

## 2. Select exactly one document

List the project corpus, then inspect every plausible candidate:

```text
yoke strategy doc list --project "$ITEM_PROJECT" --json
yoke strategy doc get SLUG --project "$ITEM_PROJECT" --json
```

Selection precedence is deterministic:

1. An exact slug explicitly identified in the item artifacts as the
   execution document.
2. Otherwise, one unique project document whose slug and current content
   match the item's title, requested outcome, and stated parent-plan
   relationship.

The result must be exactly one unarchived document in the Blitz item's
project. A corpus containing one unrelated document is not a match. If zero
or multiple candidates remain, stop at `refining-idea`, release the item work
claim, and ask the operator to name the execution-document slug. Do not guess,
create child items, copy a candidate into the item body, or create a new
strategy document without explicit operator direction.

Before linking, confirm the selected document can cold-start `/yoke blitz`.
It must state:

- required outcomes and explicit slice boundaries;
- affected areas and coordination dependencies;
- verification and delivery actions;
- unresolved decisions;
- the parent-strategy relationship, including an explicit no-parent statement
  when applicable.

If those facts are incomplete, stop for document-plan repair and do not link
or advance.

## 3. Link through the registered operation

For a new selection, invoke `strategy.execution.link` through its adapter:

```text
yoke strategy execution link "PREFIX-$ITEM_NUM" \
  --slug "$EXECUTION_SLUG" --project "$ITEM_PROJECT" --json
```

The operation is the only Refine write to `item_strategy_docs`. Do not
reconstruct the row with SQL or a lower-level helper.

## 4. Verify the execution read

Re-read through `strategy.execution.get`:

```text
yoke strategy execution get "PREFIX-$ITEM_NUM" \
  --project "$ITEM_PROJECT" --json
```

Require all of the following before status advancement:

- `execution.item.workflow_id` is `blitz`;
- `execution.execution_document.slug` equals `EXECUTION_SLUG`;
- `execution.execution_linked_at` is non-empty;
- the execution projection contains one document object, not a copied item
  body or child-item plan;
- `execution.item_claim` still identifies the current Refine item claim.

Record `EXECUTION_SLUG` for the final summary. After the lifecycle transition
and item-claim release, hand off with:

```text
Next step: /yoke blitz PREFIX-$ITEM_NUM
Execution document: $EXECUTION_SLUG
```
