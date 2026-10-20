# Dash — merge

Clean HEAD must match every accepted verdict. Never hand-merge, force-push or bypass CI. Print the wait shape, then run the printed command once:

```text
yoke watch merge --print-streaming-pair merge-item -- ITEM --wait --result "<result>" --verification "<proof>"
```

- Relay-launched: arm, report the PR and the pending landing, stop. The landing notice wakes you to rerun.
- `integration_dependency_blocked`: checkpoint, park naming the blocker, rerun after it lands.
- Candidate review pending: report the request id and wait; you cannot clear it.
- Exit 0 is not done; read the `[close-out]` block. Exit 9 names its recovery; a red check means fix, commit, reverify. Wait budget exhausted: checkpoint, park, keep the claim.
- Before any correction: `yoke github merge-queue hold ITEM --json`.

Selected deployment posture: merge with `yoke merge item ITEM --skip-status --json`, then deliver through the item's flow (`.yoke/docs/agents/rules/delivery.md`). A steering-batched worker starts no run.

Next: [close-out](close-out.md).
