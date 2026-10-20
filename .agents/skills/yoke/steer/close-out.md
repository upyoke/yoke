# Steer — settle, hand off, release

1. Refresh Live status with owners and the successor's next action.
2. Stop the watcher and any `keep steering` task.
3. Settle or hand off every pending landing, run and worker.
4. Release only this session's holds, then recheck:

```text
yoke claims work holder-list --session-id-filter {SESSION_ID} --json
yoke claims steering release {CLAIM_ID} --reason "steer close-out"
yoke claims work release --all-mine --reason "steer close-out"
```

A failed release keeps its lock; never report a clean close-out.

## Surface disable marks

Disable only on a classified vendor signature; enable after one cheap canary.

```text
yoke session-control surface-policy disable --project {_project} --machine M --surface S --reason vendor_signature
yoke session-control surface-policy enable --project {_project} --machine M --surface S
```
