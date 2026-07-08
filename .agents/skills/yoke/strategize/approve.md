# Approve

Write approved SML changes to the DB authority, render + commit the refreshed views, check frontier implications, and emit the SMLChangeApproved event. If all changes were deferred, skip writing and proceed directly to finalize.

## Prerequisites

This phase receives inline context from the Propose phase (propose.md):

- `## Proposed SML Changes` -- the full set of drafted changes grouped by file
- `## Approval Status` -- the operator's approval decisions (decision, counts, approved/deferred lists)

## Step 0: Check for Deferred-All Path

If the Approval Status decision is `deferred`, skip directly to Step 5 (emit event with outcome `changes_deferred`) and then proceed to the Finalize phase (finalize.md). No files are written, no commit is created, no frontier check is needed.

If the decision is `aborted`, release the STRATEGIZE process work claim and stop the entire strategize pipeline. Do not proceed to finalize.

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "strategize_abort",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

## Step 1: Write Approved Changes to the DB Authority

For each approved change, write the target doc through the compare-and-swap replace path. Process one doc at a time.

### 1a. Read the Current Doc and Its Base

Before modifying any SML doc, read its current content and note the row's `updated_at` — that value is the CAS base the write must carry:

```bash
yoke strategy doc get LANDSCAPE --json   # capture .result.content and .result.updated_at
```

### 1b. Author and Replace

Author the full updated doc content (apply every approved change for this doc), write it to a scratch file with the Write tool, then replace:

```bash
yoke strategy doc replace LANDSCAPE \
  --content-file /tmp/strategize-LANDSCAPE.md \
  --base-updated-at "<updated_at from 1a>" \
  --target-root "$REPO_ROOT"
```

**One doc at a time.** Do not batch changes across docs. Complete all changes for one doc before moving to the next.

Each successful replace auto-renders the latest full strategy corpus into the target checkout. The DB write still touches only the one named doc row; the local `.yoke/strategy/*.md` view refreshes all current strategy docs from the DB.

If the response is the typed `replace_conflict` error, the row moved after your 1a read (another writer landed). Re-run 1a to get the fresh content + base, re-apply your approved changes onto it, and replace again. Never retry with the stale base.

### 1c. Verify Each Write

The replace response reports `old_bytes`/`new_bytes` and the new `updated_at`. Confirm the byte delta matches the intended change size, then read the doc back (`yoke strategy doc get <SLUG>`) and confirm:

- The intended changes are present
- No unintended content was lost or corrupted
- The doc's overall structure remains intact

If verification fails, re-apply via 1a→1b (fresh base each time).

### 1d. MISSION Guard

**Do not replace MISSION** unless the Approval Status explicitly includes approved changes for it. If MISSION changes appear in the approved list but the operator did not explicitly confirm them during the normative filter (Research phase) or change approval (Propose phase), skip them and note:

```
Skipped: MISSION changes require explicit operator approval. These were not confirmed.
```

## Step 2: Record the Applied Changes

The DB write landed and `doc replace` refreshed the local rendered views. **Do not commit the views** — `.yoke/strategy/` is gitignored (the seeded `.yoke/.gitignore` `strategy/` rule), so the DB write is already the durable record and there is nothing to stage. The `SMLChangeApproved` event (Step 5) is the audit trail.

```bash
# .yoke/strategy/*.md are gitignored local caches — no commit. The DB row
# (and the SMLChangeApproved event below) is the durable record.
_commit_sha=""
```

### 2c. Collect Changed Docs List

Build the list of docs that were actually replaced for event context:

```
_files_changed = list of SML docs that received writes (e.g., "LANDSCAPE.md, VISION.md")
```

## Step 3: Checkpoint 4 -- Frontier Implication Check

Present the implications of the approved changes on the current frontier (planned and in-flight items).

### 3a. Gather Frontier Items

```bash
_frontier=$(python3 -m yoke_core.cli.db_router query "SELECT id, title, status FROM items WHERE project_id = ${_project_id} AND status NOT IN ('idea','done','cancelled','failed','stopped') ORDER BY status, id")
```

### 3b. Analyze Implications

For each frontier item, assess whether the approved SML changes affect it:

- Does the item align with the updated strategic direction?
- Does any change make an active item less relevant or more urgent?
- Are there new gaps that the current frontier does not cover?

### 3c. Present Implications

```
## Frontier Implications

The following SML changes were applied (DB rows updated; gitignored views re-rendered):
{brief list of changes}

### Impact on Current Frontier

{for each affected frontier item:}
- **YOK-{N}: {title}** ({status}) -- {impact assessment: aligned / needs review / deprioritize}

### New Gaps
{any strategic gaps revealed by the changes that have no current frontier item}

### No Impact
{frontier items unaffected by these changes, if any}

Reply in chat:

- **acknowledged** (or "looks good", "continue") to proceed to finalize
- describe concerns or call out specific items freeform and I'll discuss them with you before continuing
```

Print the frontier-implications block and the prompt above as ordinary chat/markdown output. Do **not** escalate this checkpoint to a harness chooser or selection UI -- the implications analysis is too long-form for one and follow-up discussion must stay conversational.

### Handle Operator Response

Interpret the operator's freeform reply:

- **Acknowledged** (e.g., "acknowledged", "continue", "looks good"): record the checkpoint outcome as `cp4:acknowledged` and proceed to Checkpoint 5 (if applicable) or Step 5.
- **Discuss implications**: address the operator's concerns conversationally in chat. After the discussion, restate the checkpoint with the same plain-language prompt and loop until the operator acknowledges. Record the final outcome as `cp4:acknowledged` once the discussion settles.

## Step 4: Checkpoint 5 -- Tradeoff Resolution (Conditional)

**Only present this checkpoint when ambiguity remains** after the frontier implication check. Ambiguity indicators:

- Multiple frontier items flagged as "needs review"
- Conflicting priorities between approved changes and active work
- The operator raised concerns during Checkpoint 4 discussion

If none of these indicators are present, skip directly to Step 5.

### 4a. Present Tradeoff

```
## Tradeoff Resolution

The approved changes create tension between:
- {tension A: e.g., "new strategic direction X vs active work on Y"}
- {tension B, if applicable}

### Options
{present 2-3 resolution paths with tradeoffs, each with a short, semantic label such as `finish_current_generation_first` or `resequence_frontier_after_update`}

Reply in chat with the resolution you want (by label, by description, or with a freeform alternative). I'll confirm in chat before moving on.
```

Print the tradeoff block and the prompt above as ordinary chat/markdown output. Do **not** escalate this checkpoint to a harness chooser or selection UI -- the tradeoff analysis and any proposed alternative need conversational room.

### Handle Operator Response

Interpret the operator's freeform reply:

- **Pick one of the drafted options**: record the chosen semantic label (e.g., `finish_current_generation_first`) as `_tradeoff_resolution`.
- **Freeform alternative**: if the operator proposes a new path, confirm the label and short description back in chat, then record the agreed label as `_tradeoff_resolution`.
- **Discuss first**: address concerns conversationally, then re-state the options and loop until the operator picks a path.

Keep `_tradeoff_resolution` as a semantic string that reads meaningfully in the finalize summary and the `StrategizeCompleted` event -- never a numeric selection index.

## Step 5: Emit SMLChangeApproved Event

```bash
yoke events emit \
 --name "SMLChangeApproved" \
 --kind lifecycle \
 --type strategize \
 --source-type skill \
 --severity STATUS \
 --outcome completed \
 --project "${_project}" \
 --context "{\"commit_sha\":\"${_commit_sha}\",\"files_changed\":[${_files_list}],\"changes_applied\":${_applied_count},\"changes_deferred\":${_deferred_count},\"outcome\":\"${_outcome}\"}"
```

Where:
- `_commit_sha` is retained as `""` — the rendered views are gitignored local caches, not committed, so there is no commit hash. The field stays in the event context (always empty) for backward compatibility with existing `SMLChangeApproved` consumers.
- `_files_list` is a JSON array of changed filenames (e.g., `"LANDSCAPE.md","VISION.md"`)
- `_applied_count` is the number of changes written to disk
- `_deferred_count` is the number of changes deferred
- `_outcome` is one of: `changes_applied`, `changes_deferred`

For the deferred-all path, use:
- `_commit_sha` = `""` (same as the applied path — never a commit hash)
- `_files_list` = empty array
- `_applied_count` = `0`
- `_outcome` = `"changes_deferred"`

## Step 6: Capture Landed-Work Resolutions

The State Refresh summary (refresh.md step 2d2) printed the bounded
landed-work candidate set split into `new`, `carry_forward`, `reflected`,
and `dismissed` buckets. Before handing off to `finalize.md`, collect the
operator's resolution for the items that were still `pending` during
this session. Keep the exchange conversational: present the list as a
plain markdown chat message and accept a freeform reply — no harness
selection chooser, same discipline as every other Strategize checkpoint.

```
## Landed-Work Resolutions

These landed items still owe a MASTER-PLAN.md reflection or explicit
dismissal. For each, reply with one of:

- **reflected** — the SML change(s) you just approved address this landing
- **dismissed: <reason>** — no SML change needed (explain why)
- **defer** — leave as pending, revisit next session

{render the pending bucket from `_carry_json` so the operator sees
 yok_id, title, priority, first_seen_at, and how old the pending state is}

You can reply in any freeform shape (e.g. "reflected: YOK-N;
dismissed: YOK-N (internal refactor, no landscape impact); defer the
rest"). I'll normalize the answer before recording.
```

**Rules:**
1. On the `changes_applied` path, any `reflected` answer must correspond to
 a landing that an applied SML change actually addresses. If the operator
 marks something as reflected but no applied change mentions it, ask one
 clarifying question before recording.
2. On the `changes_deferred` path, **`reflected` is not allowed** —
 deferred sessions have no applied changes to bind to. Accept only
 `dismissed` and `defer`. Reflected items here would break the
 reflected-requires-applied-change invariant.
3. `defer` is a no-op — do not add the item to either list; `finalize.md`
 leaves its state as `pending`.
4. Normalize the operator's answer into two shell-space-separated lists of
 `YOK-N` ids plus a dismissal reason, then pass to finalize.md as
 `_reflected_item_ids`, `_dismissed_item_ids`, and `_dismissed_reason`.

```bash
_reflected_item_ids="${_reflected_item_ids:-}" # e.g. "YOK-N YOK-N"
_dismissed_item_ids="${_dismissed_item_ids:-}" # e.g. "YOK-N"
_dismissed_reason="${_dismissed_reason:-operator dismissal}"
```

If the `pending` bucket is empty, skip this step silently.

## Output Context

This phase produces the following inline context for the Finalize phase (finalize.md):

- `_commit_sha` -- retained as `""` (views are gitignored, never committed)
- `_files_changed` -- list of modified SML files
- `_applied_count` -- number of changes applied
- `_deferred_count` -- number of changes deferred
- `_outcome` -- `changes_applied` or `changes_deferred`
- `_reflected_item_ids` -- carry resolutions (applied path only)
- `_dismissed_item_ids` -- carry resolutions (either path)
- `_dismissed_reason` -- rationale text for dismissals
- `_tradeoff_resolution` -- operator's tradeoff decision (if Checkpoint 5 was presented)
