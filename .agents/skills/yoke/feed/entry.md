# Feed — enter and dispatch

Parse `_no_new_items` (default false), ordered `_scope_ids` (default []),
`_scope_mode` (scoped/frontier), `_model` (override or empty session default)
and `_mode` (no-new-items/default).

```sh
yoke sessions touch --mode feed
```

Acquire exclusive FEED process claim. The project shares its
`strategy-control-plane:<project>` conflict group with Strategize:

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "process", "process_key": "FEED", "conflict_group": "<project>"},
  "intent": "feed_run",
  "payload": {
    "target": {"kind": "process", "process_key": "FEED", "conflict_group": "<project>"},
    "reason": "feed_run"
  }
}
```

`claim_conflict`: explain that another Feed/Strategize session owns this project;
wait for its completion or have it ended. Abort before FeedStarted or dispatch.

No strategy-file path claims: `strategy_docs` in the project DB is authority;
`.yoke/strategy/` is a gitignored render. FEED claim authorizes document replaces
and excludes another session's ingest. Before a strategy write read its
`--help`; exact contracts: `.yoke/docs/reference/db-reference/functions-project-configuration.md`.

**Every abort after acquisition releases FEED before exiting**.
Use the acquired integer `<claim-id>` in both places:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim-id>},
  "intent": "feed_abort",
  "payload": {"claim_id": <claim-id>, "reason": "released"}
}
```

Emit start after successful acquisition:

```sh
yoke events emit --name FeedStarted --kind lifecycle --type feed --source-type skill --severity STATUS --outcome started --project <project> --context '{"model":"<model>","mode":"<mode>"}'
```

Then follow Gather → Decide → Materialize → Reconcile → Summarize.
Gather supplies current strategy, target artifacts, graph and landing impact;
Decide supplies updates/actions/edges; Materialize updates before filing;
Reconcile persists owned graph facts; Summarize reports exact rows/coherence,
emits completion and releases FEED.
