# Worker launch

Preview, then create; no other path after a refusal. The server composes item
mandates. Choose `--level` per [model-selection.md](model-selection.md).

```text
yoke session-control launch preview --project {_project} --level {_level} --json
yoke session-control launch create --project {_project} --item {ITEM} --idempotency-key "steer:{_project}:{ITEM}:{_level}" --json
yoke session-control launch create --project {_project} --level {_level} --raw-instructions --stdin --idempotency-key "steer:{_project}:raw:{_level}:{_purpose}" --json < MANDATE_FILE
yoke session-control launch get {LAUNCH_ID} --json
yoke session-control launch reconcile {LAUNCH_ID} --json
yoke session-control launch retry {LAUNCH_ID} --json
```

Create only when preview says `launchable=true`. A failed launch is reconciled
or retried, never created again. Confirm a registered session,
then `yoke claims work holder-get PREFIX-N`. Raw mandates must forbid
deployment runs and require `DONE` through `yoke say --steering --stdin`.

## Rework

For failed delivery QA, follow [failed item recovery](../../../../.yoke/docs/verification/failed-item-qa.md)
for diagnosis, correction ownership, delivery dependencies and retest scope.

```text
yoke lifecycle transition PREFIX-N --to implementing --reason "steering rework: correction"
```

A live holder gets a `REWORK PREFIX-N` message and transitions itself; never
seize its claim. With no holder, acquire the claim, transition, then launch.
