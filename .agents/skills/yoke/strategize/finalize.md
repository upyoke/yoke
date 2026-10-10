# Strategize — carry, checkpoint, audit and release

Compile current-session provenance: applied change summary or all-N-deferred,
consulted evidence source types, actual checkpoint outcomes cp0–cp4 and cp5's
semantic choice only if presented. Retain FULL deferred change entries,
including text/evidence/approval status, for the existing audit context.

## Resolve carry first

Only applied sessions may mark reflected, bound to actual applied changes.
Either path may mark operator-dismissed items with their recorded reason.
Empty lists do nothing; deferred reflected list stays empty and pending survives.

```sh
yoke strategy carry mark --project <project> --state reflected --reason "<applied SML change identity>" --items <public-ref>
yoke strategy carry mark --project <project> --state dismissed --reason "<operator reason>" --items <public-ref>
```

Select the applicable operation(s), read back results, and count successful
marks as carry_reflected/carry_dismissed rather than shell-word guesses.

## Canonical checkpoint, then telemetry

```sh
yoke strategy checkpoint record --project <project> --kind strategize
yoke events emit --name StrategizeCompleted --kind lifecycle --type strategize --source-type skill --severity STATUS --outcome completed --project <project> --context '<provenance-json>'
```

Record checkpoint even on deferred/no-change sessions. That project's state
row bounds future refresh/drift windows; event timestamps are only audit.

Provenance context: files_changed (JSON array), changes_applied/deferred (ints),
change_summary (string), evidence_sources (array), checkpoints (semantic
outcomes), outcome, tradeoff_resolution (or empty), carry_reflected/dismissed,
and deferred_changes (complete deferred entries; empty when none).
The existing event context accepts these records; no strategy write/new
assignment registry is needed to preserve a deferred proposal.

## Release even when deferred

Substitute the acquired integer claim id:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim-id>},
  "intent": "strategize_complete",
  "payload": {"claim_id": <claim-id>, "reason": "completed"}
}
```

Surface release error but still print the session summary.

## Operator summary

Outcome; durable DB rows/SMLChangeApproved plus checkpoint/audit identities;
applied changes or deferred exact entries; evidence; each presented checkpoint
outcome; carry reflected/dismissed counts and still-pending state; next action.
Views remain gitignored; board rebuild is manual. Revisit when strategy changes.

Deferred proposals are retrievable through the project-scoped completed event:
`yoke events query --event-name StrategizeCompleted --project <project> --limit 1 --json`.
Keep its event identity in the summary so later sessions can recover the exact
deferred entries, rather than relying only on counts.
