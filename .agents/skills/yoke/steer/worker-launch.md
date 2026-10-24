# Worker launch

Preview, then create; no other path after a refusal. Pass no selection flags:
routing picks the level from the item's stage, then surface, model, effort
and machine; the server writes mandates.

```text
yoke session-control launch preview --project {_project} --item {ITEM}
yoke session-control launch create --project {_project} --item {ITEM} --idempotency-key "steer:{_project}:{ITEM}" --json
yoke session-control launch get {LAUNCH_ID}
yoke session-control launch reconcile {LAUNCH_ID}
yoke session-control launch retry {LAUNCH_ID}
```

Exceptions: [level](model-selection.md), [placement](../../../../.yoke/docs/agents/level-launches.md#overrides).
Raw itemless launches swap `--item` for `--level LEVEL --raw-instructions
--stdin < MANDATE_FILE`, key `steer:{_project}:raw:{_purpose}`.

Create only when preview says `launchable=true`. Reconcile or retry a failed
launch, never recreate it. Confirm the holder:
`yoke claims work holder-get PREFIX-N`. Raw mandates must forbid
deployment runs and require `DONE` through `yoke say --steering --stdin`.

## Rework

Failed delivery QA: diagnose, own the correction and set retest scope per
[failed item recovery](../../../../.yoke/docs/verification/failed-item-qa.md).

```text
yoke lifecycle transition PREFIX-N --to implementing --reason "steering rework: correction"
```

A live holder gets a `REWORK PREFIX-N` message and transitions itself; never
seize its claim. With no holder, acquire the claim, transition, then launch.
