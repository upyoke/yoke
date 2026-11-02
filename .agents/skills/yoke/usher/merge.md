# Usher — merge

Land one item at a time; generated-task items use
[merge-generated-tasks](merge-generated-tasks.md).

```text
yoke watch merge --print-streaming-pair merge-item -- PREFIX-N --skip-status --wait
```

Run the printed command once.

`--skip-status` postpones only `done`: the item still moves to `release` and its work claim is released. Merge each step of multi-step work as its own item.

0 with `landing_pending`: wait, rerun. 3: [conflicts](merge-conflicts.md).
6: release `handoff-to-usher`. 9: queue wait. Else roll back if unlanded (`yoke lifecycle transition`
to the pin's rollback target),
release `usher-halt-merge-failure` (unknown codes `usher-halt-unexpected`).

```text
yoke claims work release --item PREFIX-N --reason usher-halt-merge-failure --json
```

Cancelled checks: rerun the same merge on the same head.

Failing or flaky tests: `.yoke/docs/agents/rules/verification.md#failing-or-flaky-tests`.
