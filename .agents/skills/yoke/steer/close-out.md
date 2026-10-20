# Steer — settle, hand off, release

1. Refresh Live status with owners and the successor's next action.
2. Stop the watcher and any `keep steering` task.
3. Settle or hand off every pending landing, run and worker. Parked release
   members stay owned: never release, terminate or run QA for them.
4. Inventory all three holding kinds, release only this session's holds
   (steering pair, coordination, then work), and repeat the inventories:

```text
yoke claims steering list --session-id {SESSION_ID} --active-only --json
yoke claims coordination-claim list --session-id {SESSION_ID} --active-only --json
yoke claims work holder-list --session-id-filter {SESSION_ID} --json
yoke claims steering release {CLAIM_ID} --reason "steer close-out"
yoke claims coordination-claim release --project {_project} --key KEY --reason "steer close-out"
yoke claims work release --all-mine --reason "steer close-out"
```

A failed release keeps its lock; never report a clean close-out. Run
`/yoke wrapup` only when the operator asks.

## Surface disable marks

Disable only on a classified vendor signature; enable after one cheap canary.

```text
yoke session-control surface-policy disable --project {_project} --machine M --surface S --reason vendor_signature
yoke session-control surface-policy enable --project {_project} --machine M --surface S
```
