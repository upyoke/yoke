# Items Function Catalog

Read [envelope and authority](functions.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `items.block.run` | `none` |
| `items.cancel.run` | `none` |
| `items.create` | `none` |
| `items.dependency.add` | `none` |
| `items.dependency.list` | `none` |
| `items.dependency.remove` | `none` |
| `items.dependency.update` | `none` |
| `items.deployment_flow.claim_default` | `item` |
| `items.detail.get` | `none` |
| `items.freeze.run` | `none` |
| `items.get.run` | `none` |
| `items.github_done_sync` | `none` |
| `items.github_sync` | `none` |
| `items.list.run` | `none` |
| `items.merge_provenance.operator_correct` | `none` |
| `items.overview.list` | `none` |
| `items.progress_log.append` | `item` |
| `items.progress_log.get` | `none` |
| `items.scalar.update` | `item` |
| `items.search.run` | `none` |
| `items.section.delete` | `item` |
| `items.section.get` | `none` |
| `items.section.upsert` | `item` |
| `items.structured_field.append_addendum` | `item` |
| `items.structured_field.replace` | `item` |
| `items.structured_field.section_append` | `item` |
| `items.structured_field.section_upsert` | `item` |
| `items.thaw.run` | `none` |
| `items.unblock.run` | `none` |
| `lifecycle.repair_status.execute` | `steering` |
| `lifecycle.skip.record_recoverable_substrate` | `item` |
| `lifecycle.transition.execute` | `item` |
| `readiness.check.run` | `none` |
| `readiness.prd_validate.run` | `none` |
| `readiness.repair_claim_coverage` | `item` |
| `readiness.repair_stale_count` | `item` |
| `resync.compare_prefetch` | `none` |
| `resync.epic_task_body` | `none` |
| `resync.epic_task_github_issue_set` | `none` |
| `resync.epic_task_repair_read` | `none` |
| `resync.item_lookup` | `none` |
| `resync.linkage_roster` | `none` |
| `resync.linkage_rows` | `none` |
| `status.run` | `none` |

## Creation and structured writes

Every create chooses the target project, pinned workflow and allowed typed entry
surface. Non-web filing reads Before creation instructions with
`yoke workflow execution-instruction resolve --workflow W --project P --full`
and explicitly sends `execution_instructions_considered: true`; CLI adapters
never attest for the caller. Web forms render their own instructions; promotion,
dry-run and disposable test targets retain their exemptions. The receipt echoes
the accepted attestation. Missing attestation refuses before creation.

Item body is rendered from stored fields. Full replacement preserves
empty/shrinkage/freeze guards; additive transforms preserve prior content.
Field-target section upsert requires the named stored field and heading level;
section operations without a field address item sections. Verify the returned
field/section and line counts. Request JSON on the original mutation.

```json
{"function":"items.structured_field.replace",
 "target":{"kind":"item","public_ref":"PREFIX-N"},
 "payload":{"field":"spec","content":"# Spec\n\n..."},
 "options":{"sync_github_body":true}}
```

Progress Log append stamps the timestamp, preserves entries and upserts at
ordering 200. Entries are current-state checkpoints; task-graph planning fields
remain reserved for generated-task workflows. Scalars validate their own fields.
Lifecycle transitions enforce the exact pin, source stage and target gates;
terminal status is pipeline-owned, never a scalar shortcut.

```json
{"function":"items.progress_log.append",
 "target":{"kind":"item","public_ref":"PREFIX-N"},
 "payload":{"headline":"Session checkpoint","content":"Current state..."}}
```

Readiness and resync return observed evidence and named repairs; read-shaped
previews never authorize an unrequested mutation. [Domain contract](items-and-epics.md).
