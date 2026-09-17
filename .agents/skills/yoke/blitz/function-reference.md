# /yoke blitz — registered operation authority

Read this when you need a Blitz operation's function id or exact adapter
shape. It is a lookup, not a phase step.

## Registered operation authority

Use the registered function id as the operation authority. The `yoke`
commands taught later are adapters for these envelopes:

| Function id | Target and payload | CLI adapter |
|---|---|---|
| `items.detail.get` | Item target; optional `include` naming content sections (`narrative`, `body`, `progress_log`) — omit for the posture plus `content_index`, which names each stored section and the read that returns it | `yoke items detail get ITEM --json` |
| `workflows.item.get` | Item target; empty payload; centrally resolved effective policies | `yoke workflows item get ITEM --json` |
| `strategy.execution.get` | Blitz item target; empty payload | `yoke strategy execution get ITEM --json` |
| `strategy.doc.get` | Project target; `slug` | `yoke strategy doc get SLUG --project PROJECT --json` |
| `direct_workflow.blitz.survey` | Item target; `paths` plus optional `integration_target` | `yoke direct-workflow blitz survey ITEM --path PATH --json` |
| `lifecycle.transition.execute` | Item target; `source_status`, `target_status`, and `reason` | `yoke lifecycle transition ITEM --from STATUS --to STATUS --reason TEXT` |
| `strategy.coordination.append` | Project target; `slug`, `section`, and `entry` | `yoke strategy coordination append SLUG --section NAME --entry TEXT --project PROJECT` |
| `strategy.doc.replace` | Project target; `slug`, full `content`, `base_updated_at`, and shrink-guard posture | `yoke strategy doc replace SLUG --base-updated-at TS --content-file PATH --project PROJECT` |
| `strategy.claim.release` | Blitz item target; optional `reason` | `yoke strategy claim release ITEM --reason TEXT` |
| `claims.work.release` | Current item or claim target; `reason` | `yoke claims work release --item ITEM --reason TEXT` |

The survey has no item-claim precondition. Strategy reads, coordination
appends, document replacement, lifecycle transitions, and claim release
remain their own registered operation families; they are not hidden
Blitz-survey payloads. Execution-document linking belongs to `/yoke refine`
through `strategy.execution.link`, before this skill begins.

Worktree preparation and slice merging are each a
retained tool-shaped operation, because both act on the local checkout
rather than on control-plane state alone:

```text
yoke direct-workflow worktree prepare ITEM --workflow blitz
yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait
```

The first delegates to the local engine worktree preflight. The second is the
standalone-item merge boundary shared with Dash. With `--print-streaming-pair`
its watcher prints — and never runs — the shape the caller's manifest
capability selects: a verified route gets the background subscription, while
no route or an unknown answer gets one foreground invocation you run. Inspect
queue liveness with `yoke github merge-queue readiness ITEM --json`, never a
bare automerge field, and clear a live candidate with
`yoke github merge-queue hold ITEM` before correcting it. Non-queue routes
still land inline. Each command has no registered `direct_workflow.*` function
id — use them verbatim; do not invent function ids for them. Contract:
[`docs/archive/decisions/standalone-item-merge.md`](../../../../docs/archive/decisions/standalone-item-merge.md).

