# Finalize

Record the strategy checkpoint (the "last refresh" marker consumed by Phase 1 delta bounding and drift review) plus comprehensive provenance via the StrategizeCompleted telemetry event, then print a session summary.

## Prerequisites

This phase receives inline context from the Approve phase (approve.md):

- `_files_changed` -- list of modified SML files (empty if deferred)
- `_applied_count` -- number of changes applied (0 if deferred)
- `_deferred_count` -- number of changes deferred
- `_outcome` -- `changes_applied` or `changes_deferred`
- `_tradeoff_resolution` -- operator's tradeoff decision (empty if Checkpoint 5 was skipped)

And accumulated context from earlier phases:

- Problem framing from the State Refresh phase (refresh.md)
- Evidence sources from the Research phase (research.md)
- Checkpoints used throughout the pipeline

## Step 1: Compile Provenance

Gather the full provenance record from the session. This is the audit trail for what happened and why.

### 1a. Change Summary

Build a concise summary of what changed (or was deferred):

```
_change_summary = if outcome is changes_applied:
 "{N} changes applied to {file list}: {brief description of each change}"
else:
 "All {N} proposed changes deferred to next session"
```

### 1b. Evidence Sources

Compile the list of evidence sources consulted during the Research phase:

```
_evidence_sources = list of source types used, e.g.:
 "git_log, board_state, epic_tasks, sml_diff"
```

### 1c. Checkpoints Used

Record which checkpoints were presented and their outcomes:

```
_checkpoints = list of checkpoint outcomes, e.g.:
 "cp0:confirmed, cp1:specific, cp2:filtered_3_of_5, cp3:approved_all, cp4:acknowledged"
```

Include Checkpoint 5 only if it was presented:

```
 "cp5:finish_current_generation_first" (or omit if skipped)
```

## Step 1d: Record Landed-Work Carry-Forward Resolutions

Before emitting `StrategizeCompleted`, persist the operator's decisions
about which landed items were **reflected** in the SML changes and which
were **dismissed**. The bounded candidate set was built in the State
Refresh phase (`refresh.md` step 2d2) and surfaced in the State Refresh
summary. The Approve phase (`approve.md`) should have captured, for each
proposed SML change, which landed items it addresses — that's the input
this step consumes.

Accumulate two lists during the approval phase and pass them here:

- `_reflected_item_ids` — space-separated `YOK-N` ids whose landing was
 addressed by an applied SML change. On the `changes_deferred` path,
 **this list must stay empty** — deferred sessions are not allowed to
 flip pending items to reflected.
- `_dismissed_item_ids` — space-separated `YOK-N` ids the operator
 explicitly decided are not worth an SML change (e.g. landed work is
 pure internals, no landscape impact). The dismissal reason should be
 captured in `_dismissed_reason` so the carry table has audit trail.

On `changes_applied` runs:

```bash
if [ -n "${_reflected_item_ids}" ]; then
 yoke strategy carry mark \
 --project "$_project" \
 --state reflected \
 --reason "addressed by approved SML change" \
 --items ${_reflected_item_ids}
fi
```

On **either** path (applied or deferred), dismissals are always allowed:

```bash
if [ -n "${_dismissed_item_ids}" ]; then
 yoke strategy carry mark \
 --project "$_project" \
 --state dismissed \
 --reason "${_dismissed_reason:-operator dismissal}" \
 --items ${_dismissed_item_ids}
fi
```

If both lists are empty (pure deferred session with no dismissals), do
nothing — pending items must remain pending. The operator can
always return in a later Strategize session to resolve them.

Capture the two counts for the StrategizeCompleted event context:

```bash
_reflected_count=$(echo "${_reflected_item_ids}" | wc -w | tr -d ' ')
_dismissed_count=$(echo "${_dismissed_item_ids}" | wc -w | tr -d ' ')
```

These feed `carry_reflected`/`carry_dismissed` in the StrategizeCompleted
event context so future Strategize sessions (and audit queries) can see
exactly which items were resolved and when.

## Step 2: Record the Checkpoint + Emit StrategizeCompleted Event

State first: the `strategy_checkpoints` row is the canonical "last refresh" marker for THIS project. Future strategize sessions (the State Refresh phase, refresh.md) and drift review read the latest checkpoint row to bound their delta windows — the event below is telemetry for audit, not the boundary.

```bash
yoke strategy checkpoint record --project "${_project}" --kind strategize
```

Then emit the matching telemetry event with full provenance context:

```bash
yoke events emit \
 --name "StrategizeCompleted" \
 --kind lifecycle \
 --type strategize \
 --source-type skill \
 --severity STATUS \
 --outcome completed \
 --project "${_project}" \
 --context "{\"files_changed\":[${_files_list}],\"changes_applied\":${_applied_count},\"changes_deferred\":${_deferred_count},\"change_summary\":\"${_change_summary}\",\"evidence_sources\":[${_evidence_sources}],\"checkpoints\":\"${_checkpoints}\",\"outcome\":\"${_outcome}\",\"tradeoff_resolution\":\"${_tradeoff_resolution}\",\"carry_reflected\":${_reflected_count:-0},\"carry_dismissed\":${_dismissed_count:-0}}"
```

Where:
- `_files_list` is a JSON array of changed filenames (empty `[]` contents if deferred)
- `_applied_count` and `_deferred_count` are integers
- `_change_summary` is a one-line summary string
- `_evidence_sources` is a JSON array of source type strings
- `_checkpoints` is a comma-separated string of checkpoint outcomes
- `_outcome` is `changes_applied` or `changes_deferred`
- `_tradeoff_resolution` is the resolution choice or empty string if Checkpoint 5 was skipped

**Important:** This event MUST be emitted even on the deferred-all path. The timestamp still marks "strategize happened" for delta bounding, even when no files were changed.

## Step 2b: Release STRATEGIZE Process Claim

Release the exclusive process work claim so the session can end naturally or be reused for other skills. The claim is the only lock this loop holds — releasing it reopens the strategy write window for other sessions (`yoke strategy ingest` stops bouncing).

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "strategize_complete",
  "payload": {"claim_id": <claim_id>, "reason": "completed"}
}
```

**Important:** This MUST run even on the deferred-all path. A release failure surfaces as a response error but does not block the session summary.

## Step 3: Print Session Summary

Print a human-readable summary for the operator. This is the final output of the strategize pipeline.

```
## Strategize Session Complete

**Outcome:** {changes_applied | changes_deferred}

### Changes
{if changes_applied:}
- {file}: {brief description of changes} (for each changed file)
{if changes_deferred:}
- {N} changes deferred to next strategize session

### Evidence Consulted
- {list of evidence source types}

### Checkpoints
- Checkpoint 0 (State Refresh): {outcome}
- Checkpoint 1 (Problem Framing): {outcome}
- Checkpoint 2 (Normative Filter): {outcome}
- Checkpoint 3 (Change Approval): {outcome}
- Checkpoint 4 (Frontier Implications): {outcome}
{if checkpoint 5 was presented:}
- Checkpoint 5 (Tradeoff Resolution): {outcome}

### Deferred Items
{if any changes were deferred:}
- {list of deferred changes for awareness in next session}
{else:}
- None

### Landed-Work Carry-Forward
- Reflected: {_reflected_count} item(s)
- Dismissed: {_dismissed_count} item(s)
- Still pending: see the next Strategize session — deferred sessions never
 auto-resolve pending landings

### Next Steps
{if changes_applied:}
- SML docs updated in the DB. Changes will be visible in the next board rebuild.
- Run `/yoke strategize` again when the landscape shifts or new capabilities land.
{if changes_deferred:}
- Deferred changes are recorded in the StrategizeCompleted event context (telemetry).
- Run `/yoke strategize` in your next session to revisit them.
```
