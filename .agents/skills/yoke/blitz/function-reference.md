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

Survey has no item-claim precondition. Strategy reads/writes, coordination,
lifecycle and claim release remain separate operations, rather than hidden
survey payloads. Execution-document linking is Refine's `strategy.execution.link`.

Local preparation and slice merge retain tool-shaped boundaries:

```sh
yoke direct-workflow worktree prepare ITEM --workflow blitz
yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait
```

Use them verbatim; neither has a `direct_workflow.*` function id.
Preparation delegates to local preflight. The watcher only prints the
manifest-selected command: verified wake route gets one background subscription;
missing/unknown route gets one foreground invocation. Run and hold that command
through its result. Non-queue routes land inline.

For queue liveness use `yoke github merge-queue readiness ITEM --json`;
before correcting a live candidate, use `yoke github merge-queue hold ITEM`.
The automerge flag does not prove queue readiness.
Read `yoke merge item --help` for the flag matrix.
