# Usher — merge

Land one item at a time; generated-task items use
[merge-generated-tasks](merge-generated-tasks.md).

```text
yoke watch merge --print-streaming-pair merge-item -- PREFIX-N --skip-status --wait
```

Run the printed command once.

0 with `landing_pending`: wait, rerun. 3: [conflicts](merge-conflicts.md).
6: release `handoff-to-usher`. 9: queue wait. Else roll back if unlanded (`yoke lifecycle transition`
to the pin's rollback target),
release `usher-halt-merge-failure` (unknown codes `usher-halt-unexpected`).

```text
yoke claims work release --item PREFIX-N --reason usher-halt-merge-failure --json
```

Cancelled checks: rerun the same merge on the same head.

Flakes: `.yoke/docs/github/merge-queue-landings.md#failed-merge-trains`.
