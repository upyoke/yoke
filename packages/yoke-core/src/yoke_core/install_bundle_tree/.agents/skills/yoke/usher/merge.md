# Usher — merge

Land one item at a time; generated-task items use
[merge-generated-tasks](merge-generated-tasks.md).

```text
yoke watch merge --print-streaming-pair merge-item -- PREFIX-N --skip-status --wait
```

Run the printed command once.

`--skip-status` postpones only `done`: the item still moves to `release` and its work claim is released. Merge each step of multi-step work as its own item.

0 with `landing_pending`: wait, rerun. 3: conflict. Finish the active Git
operation; never start a second one. Keep both sides' intent, regenerate
generated files, commit, rerun the same merge. Unclear intent stops for the
operator ([merge queue landings](../../../../.yoke/docs/github/merge-queue-landings.md)).
6: the merge already waited the full lock TTL; the refusal names the holding item. Check it, then rerun or release `handoff-to-usher`.
`merge_target_moved`: pin-only target moves self-recover; any other means refresh the lane and rerun.
9: queue wait. Else roll back if unlanded (`yoke lifecycle transition`
to the pin's rollback target),
release `usher-halt-merge-failure` (unknown codes `usher-halt-unexpected`).

```text
yoke claims work release --item PREFIX-N --reason usher-halt-merge-failure --json
```

Cancelled checks: rerun the same merge on the same head.

Failing or flaky tests: `.yoke/docs/agents/rules.md#failures`.
