# Strategize — enter and claim

Parse `_model` (override or empty session default), resolve this checkout's
project, then stamp mode:

```sh
yoke sessions touch --mode strategize
```

Acquire exclusive STRATEGIZE process claim for this project. FEED shares
`strategy-control-plane:<project>`; different projects may run concurrently.

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "process", "process_key": "STRATEGIZE", "conflict_group": "<project>"},
  "intent": "strategize_run",
  "payload": {
    "target": {"kind": "process", "process_key": "STRATEGIZE", "conflict_group": "<project>"},
    "reason": "strategize_run"
  }
}
```

Adapter: `yoke claims work acquire --process STRATEGIZE --project <project>`.
`claim_conflict`: explain the other Feed/Strategize holder must finish/be ended;
stop BEFORE StrategizeStarted or reading/dispatching later phases.

Claim authorizes the TARGET project's strategy replace and excludes other-session
ingest. No path claims on gitignored rendered caches.

## Common abort contract — every phase

Every operator/error abort releases the acquired claim before exiting.
Use its returned integer id in both positions:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim-id>},
  "intent": "strategize_abort",
  "payload": {"claim_id": <claim-id>, "reason": "released"}
}
```

Adapter: `yoke claims work release --process STRATEGIZE --project <project> --reason "strategize abort"`.
Release reopens the strategy write window. Later phases refer to this contract;
abort stops the whole pipeline.

After acquisition emit:

```sh
yoke events emit --name StrategizeStarted --kind lifecycle --type strategize --source-type skill --severity STATUS --outcome started --project <project> --context '{"model":"<model>"}'
```

Follow Refresh → Research → Propose → Approve → Finalize.
