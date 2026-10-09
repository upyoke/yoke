# Blitz — operation authority

Use registered function ids; command adapters build those envelopes.
Exact target/payload contracts are in the existing catalog:

- [Items/workflow runtime](../../../../.yoke/docs/reference/db-reference/functions-items.md):
  `items.detail.get`; omit `include` for posture/`content_index`, or request
  `narrative`, `body`, `progress_log`. Lifecycle transitions use
  `lifecycle.transition.execute`.
- [Workflows](../../../../.yoke/docs/reference/db-reference/functions-workflows.md):
  `workflows.item.get`, `direct_workflow.blitz.survey`.
- [Project configuration](../../../../.yoke/docs/reference/db-reference/functions-project-configuration.md):
  `strategy.execution.get`, `strategy.doc.get`, `strategy.coordination.append`,
  `strategy.doc.replace`, `strategy.claim.release`.
  Read the selected command's `--help` before a strategy write.
- [Claims](../../../../.yoke/docs/reference/db-reference/functions-claims.md):
  `claims.work.release`.

| Function id | Short adapter lookup |
|---|---|
| `items.detail.get` | `yoke items detail get` |
| `strategy.execution.get` | `yoke strategy execution get` |
| `strategy.doc.get` | `yoke strategy doc get` |
| `direct_workflow.blitz.survey` | `yoke direct-workflow blitz survey` |
| `lifecycle.transition.execute` | `yoke lifecycle transition` |
| `strategy.coordination.append` | `yoke strategy coordination append` |
| `strategy.doc.replace` | `yoke strategy doc replace` |
| `strategy.claim.release` | `yoke strategy claim release` |
| `claims.work.release` | `yoke claims work release` |

Survey has no item-claim precondition. Strategy reads/writes, coordination,
lifecycle and claim release remain separate operations, rather than hidden
survey payloads. Execution-document linking is Refine's `strategy.execution.link`.

Local preparation and slice merge are each a retained tool-shaped operation:

```sh
yoke direct-workflow worktree prepare ITEM --workflow blitz
yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait
```

Use them verbatim; each has no registered `direct_workflow.*` function id.
Preparation delegates to local preflight. The watcher prints — and never runs — the shape
selected by the manifest: a verified route gets the background subscription;
no route or an unknown answer gets one foreground invocation. Run and hold that command
through its result. Non-queue routes land inline.

For queue liveness use `yoke github merge-queue readiness ITEM --json`;
before correcting a live candidate, use `yoke github merge-queue hold ITEM`.
The automerge flag does not prove queue readiness.
Read `yoke merge item --help` for the flag matrix.
