# Steer — settle, hand off, release

Honor explicit stop promptly. Release is mark-complete, not silence or a
substitute for settling operations. Follow this order:

1. Refresh the document's Live status snapshot with runs/workers, ownership,
   receipts and exact successor action; the next seat can cold-start there.
2. Stop this session's watcher through its owning handle and remove its Codex
   keep steering schedule if present. Do not leave unowned recovery automation.
3. Settle or explicitly hand off every pending landing, deploy or worker
   before releasing its protecting lock. Reuse merge/run recovery and name
   successor. Run success is not finished member delivery:

```text
yoke deployment-runs get {RUN_ID}
yoke deployment-runs stages {RUN_ID}
```

Parked release members remain owned: do not release their claims, terminate
them, run their QA or close-out. Snapshot owners/owed work. Only an orphan
explicitly handed to this seat is yours to finish through yoke merge item.

4. Inventory all three session holdings; no one bulk call covers them:

```text
yoke claims steering list --session-id {SESSION_ID} --active-only --json
yoke claims coordination-claim list --session-id {SESSION_ID} --active-only --json
yoke claims work holder-list --session-id-filter {SESSION_ID} --json
```

5. Release only this session's remaining holds: steering pair first, each
   named coordination hold (DEPLOY is sticky), then work. Never release
   another worker's/item-owned claim or directly unlock a live paired doc.

```text
yoke claims steering release {CLAIM_ID} --reason "steer close-out"
yoke claims coordination-claim release --project {_project} --key DEPLOY:{_project} --reason "steer close-out"
yoke claims work release --all-mine --reason "steer close-out"
```

6. Repeat all inventories: empty or only deliberately recorded handoffs.
   Failed release/unsafe unsettled operation retains its lock and names exact
   exception/recovery; never report clean close-out. Explicit operator release
   instruction is already authority. Wrapup only when asked for session close.

Heavy transcript/quiet fleet favors orderly snapshot+seat handoff to a fresh
session. Choose actual wait cadence with prompt-cache cost in mind: dense
when active or infrequent batched passes, no just-expired repeated transcript.

## Surface disable marks

Manual vendor circuit breaker only: no failure counter/autotrip/auto-clear/
timer probing. Classified quota or broken-harness signature disables that
machine/surface and rebalances new launches. Unclassified failure escalates
instead; do not disable a healthy harness for a system defect.

```text
yoke session-control surface-policy disable --project {_project} --machine M --surface S --reason vendor_signature
yoke session-control surface-policy enable --project {_project} --machine M --surface S
```

Enable only after one successful cheap canary. Marks gate new launches/native
resume spawns; in-flight sessions stay up.
