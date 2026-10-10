# Tasks Function Catalog

Read [envelope and authority](functions.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `conduct.epic.proceed_triage_handoff` | `epic` |
| `conduct.epic_task.update_status` | `none` |
| `epic_tasks.list.run` | `none` |
| `workflow_item.epic_dispatch_chain.advance` | `epic` |
| `workflow_item.epic_dispatch_chain.get` | `none` |
| `workflow_item.epic_dispatch_chain.list` | `none` |
| `workflow_item.epic_dispatch_chain.refresh_activation` | `epic` |
| `workflow_item.epic_dispatch_chain.update` | `epic` |
| `workflow_item.epic_progress_note.append` | `epic` |
| `workflow_item.epic_progress_note.list` | `none` |
| `workflow_item.epic_task.add` | `epic` |
| `workflow_item.epic_task.body_get` | `none` |
| `workflow_item.epic_task.body_replace` | `epic` |
| `workflow_item.epic_task.file_add` | `epic` |
| `workflow_item.epic_task.get` | `none` |
| `workflow_item.epic_task.history_insert` | `epic` |
| `workflow_item.epic_task.metadata_update` | `epic` |
| `workflow_item.epic_task.reassign` | `epic` |
| `workflow_item.epic_task.remove` | `epic` |
| `workflow_item.epic_task.review_get` | `none` |
| `workflow_item.epic_task.review_insert` | `epic` |
| `workflow_item.epic_task.review_list` | `none` |
| `workflow_item.epic_task.review_seed` | `epic` |
| `workflow_item.epic_task.scope_finalize` | `epic` |
| `workflow_item.epic_task.scope_no_files` | `epic` |
| `workflow_item.epic_task.scope_reopen` | `epic` |
| `workflow_item.epic_task.scope_repair_legacy` | `epic` |
| `workflow_item.epic_task.simulation_get` | `none` |
| `workflow_item.epic_task.simulation_upsert` | `epic` |
| `workflow_item.epic_task.split` | `epic` |
| `workflow_item.epic_task.submission_receipt_get` | `none` |
| `workflow_item.epic_task.update_status` | `epic` |

## Generated task and dispatch contracts

The parent epic claim authorizes task writes. Body replacement preserves guards
and reports line counts. Split preserves dependency intent and renumbers
downstream tasks atomically; reassign changes lane assignment; remove cascades
task dependency edges. Metadata updates validate task fields. Parent planning
persists decomposition; workers never invent unrelated backlog children.

Progress notes are keyed by parent/task/note number. Review seed is idempotent
and advances implementing to reviewing-implementation; a stored PASS review
advances to reviewed-implementation. Review get names absence; list counts rows,
not lines in multi-line bodies. Manual status updates never bypass terminal
pipeline gates.

```json
{"function":"workflow_item.epic_task.body_replace",
 "target":{"kind":"epic_task","public_ref":"PREFIX-N","task_num":5},
 "payload":{"content":"..."}}
```

Simulation is parent-persisted against the epic target, no task number, with
phase, complete report body and optional head_sha. CLI --head-sha binds the
verified code commit when no clean epic lane supplies it. Parsed two-line
verdict/epic must match dispatch; every actual phase attempt remains durable.
Phase selection uses JSON values independent of whitespace; simulation-get
returns the latest exact phase attempt. Receipt names requirement_id, run_id,
verdict and verified=true after exact-run readback, without body. Identity or
verdict mismatch refuses before writing; readback failure returns known ids
without retrying. Requirement/run creation failures preserve their underlying
refusal and recovery. Consume this served contract at its declared floor. Submission
receipt get validates the latest new PASS receipt after the supplied note count;
bad/missing fields refuse rather than treating narrative as proof.

Dispatch-chain reads and checkpoints retain exact lane/head/task and activation
facts. Claim and preparation handoffs belong to the pinned binding. Read the
current returned dispatch facts before choosing work; [workflow catalog](functions-workflows.md).
