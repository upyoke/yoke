# State Refresh

Reconcile the Strategic Markdown Layer with recent reality before proposing any normative changes. This phase reads current SML state, bounds the delta to inspect, gathers context, and runs two operator checkpoints.

## Step 1: Delta Bounding

Determine what changed since the last strategic refresh.

### 1a. Read the Prior Strategy Checkpoint

Scoped to this project — another project's strategize sessions must not bound this delta window. Checkpoints are `strategy_checkpoints` state rows (written by finalize Step 2 and by drift-review completion); the events ledger is telemetry-only and is not consulted:

```bash
_last_strategize=$(yoke strategy checkpoint latest --project "${_project}")
```

### 1b. Determine Delta Window

If `_last_strategize` is non-empty, the delta window starts from that timestamp. Use it to scope git log and board queries:

```bash
_since_flag="--since=\"${_last_strategize}\""
```

If `_last_strategize` is empty (no prior strategize session), fall back to the most recent SML doc write — the newest `updated_at` across the SML rows:

```bash
yoke strategy doc list   # newest updated_at among MISSION/LANDSCAPE/VISION/MASTER-PLAN
```

If that also yields nothing, use the last 14 days as the default window:

```bash
_since_flag="--since=\"14 days ago\""
```

Print the delta window for operator awareness:

```
Delta window: {start timestamp} to now
Source: {strategy checkpoint / last SML commit / default 14-day fallback}
```

## Step 2: State Gathering

Read the current SML docs from the DB authority and gather contextual information.

### 2a. Read SML Docs

Read all four SML docs:

```bash
yoke strategy doc get MISSION
yoke strategy doc get LANDSCAPE
yoke strategy doc get VISION
yoke strategy doc get MASTER-PLAN
```

Note the key sections, structure, and any dates/versions mentioned, and keep each doc's `updated_at` from `yoke strategy doc list` at hand — the approve phase needs it as the compare-and-swap base. Do NOT print full doc contents to the operator -- summarize.

### 2b. Recent Commits in Delta Window (presentation-only sample)

This is a **readability sample** — the bounded complete landed-work candidate
set is owned by step 2d2 below. Do not rely on this `head -30` cap to decide
which landings need SML reflection; it exists only so the State Refresh
summary can name a handful of recent commit subjects in prose.

```bash
git log --oneline ${_since_flag} -- . | head -30
```

Capture the commit subjects to understand what landed recently. Full
authoritative landed-work enumeration happens in step 2d2.

### 2c. Recent SML Changes

The rendered `.yoke/strategy/*.md` views are gitignored local caches, so their change history lives in the DB and the event ledger, not in git. Read each doc's last-write metadata:

```bash
yoke strategy doc list --project "$_project"
```

Each row's `updated_at` / `updated_by` shows which docs changed and how recently. The narrative of prior approved changes is the `SMLChangeApproved` / `StrategyDocReplaced` event trail (query the events surface, e.g. `yoke db read "SELECT created_at, context FROM events WHERE event_name = 'SMLChangeApproved' ORDER BY created_at DESC LIMIT 10"`).

### 2d. Board State

Query current board state for in-flight items. Display-only sample size is
capped at 30 rows — the **authoritative** landed-work candidate set is built
separately in step 2d2 via `strategize_carry`, so this query is
intentionally a readability sample, not a truth source.

```bash
_active_items=$(python3 -m yoke_core.cli.db_router query "SELECT id, title, status FROM items WHERE project_id = ${_project_id} AND status NOT IN ('idea','done','cancelled','failed','stopped') ORDER BY status, id")
# Display-only sample of recent done items. DO NOT treat as authoritative —
# the bounded complete candidate set lives in the carry helper (step 2d2).
_recent_done_sample=$(python3 -m yoke_core.cli.db_router query "SELECT id, title FROM items WHERE project_id = ${_project_id} AND status = 'done' ORDER BY id DESC LIMIT 10")
```

### 2d2. Bounded Landed-Work Candidate Set

The `head -30` commit sample in step 2b and the `LIMIT 10` done-items sample
in step 2d are **presentation-only** — the Strategize State Refresh summary
must present the **complete bounded set** of landed work that still owes a
`MASTER-PLAN.md` reflection or explicit dismissal. That set is owned by
the registered `yoke strategy carry ...` surfaces, which:

- Scans items merged within the configured horizon
 (`strategize_carry_horizon_days`, default 60) and inserts any new ones as
 `pending` carry rows (never overwrites existing state).
- Preserves items first seen in an earlier session, even after they age out
 of the horizon — so deferred or no-change Strategize sessions never
 silently drop unresolved landings.
- Distinguishes new, carry-forward, reflected, and dismissed items so the
 operator summary in step 3 can render each bucket explicitly.
- Is capped by `strategize_carry_limit` (default 200) as a safety rail; the
 summary surfaces a truncation note when the cap is hit.

Resolve the carry knobs (`$_project` already carries the checkout's
mapped project from the Constants block):

```bash
_carry_horizon=$(python3 -m yoke_core.domain.runtime_settings get strategize_carry_horizon_days 60)
_carry_limit=$(python3 -m yoke_core.domain.runtime_settings get strategize_carry_limit 200)
```

Run the register + summary step. Capture the newly discovered ids once, then
reuse that same set for both the markdown summary and the structured JSON so
the `new` bucket stays consistent across the whole session.

```bash
_carry_new_json=$(yoke strategy carry register-new \
 --project "$_project" \
 --horizon-days "$_carry_horizon" \
 --carry-limit "$_carry_limit" \
 --result-json)
_carry_new_ids=$(printf '%s' "$_carry_new_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(' '.join(str(i) for i in d.get('new_ids', [])))")
_carry_summary=$(yoke strategy carry summary \
 --project "$_project" \
 --horizon-days "$_carry_horizon" \
 --carry-limit "$_carry_limit" \
 --new-ids ${_carry_new_ids})
```

The explicit `register-new` call above is the only place that discovers new
landings in this phase. `summary` is read-only and receives the captured
`--new-ids` so the printed buckets match the structured JSON below instead of
silently downgrading fresh landings into generic carry-forward.

Capture the structured form too so step 3's summary can emit bucket counts
without re-parsing markdown:

```bash
_carry_json=$(yoke strategy carry candidate-set \
 --project "$_project" \
 --horizon-days "$_carry_horizon" \
 --carry-limit "$_carry_limit" \
 --new-ids ${_carry_new_ids})
_carry_total_pending=$(printf '%s' "$_carry_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total_pending', 0))")
_carry_new_count=$(printf '%s' "$_carry_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('new', [])))")
```

Hold onto `_carry_summary` and `_carry_json` — the first is pasted verbatim
into the State Refresh summary block (step 3), the second is the source of
truth for the change-proposal matching (approve.md) and the
resolution-marking step (finalize.md).

### 2e. In-Flight Epic Task Bodies

For in-flight epics, read task titles to understand what is currently being built:

```bash
_active_epics=$(python3 -m yoke_core.cli.db_router query "SELECT id, title FROM items WHERE project_id = ${_project_id} AND status NOT IN ('idea','done','cancelled','failed','stopped') AND type = 'epic'")
```

For each active epic, list its tasks:

```bash
yoke epic-tasks list --epic {epic-id}
```

## Step 3: Checkpoint 0 -- State Refresh Confirmation

Synthesize the gathered information into a concise state refresh summary and print it to the operator as a normal chat/markdown message. Strategize is a conversational advisory loop -- keep this checkpoint in plain chat and do **not** escalate it to any harness-specific chooser or selection UI, which would compress the long-form analysis it depends on.

### Summary Format

Print the summary inline in chat using this structure:

```
## State Refresh Summary

**Delta window:** {start} to now ({source})

### SML Current State
- **MISSION.md:** {one-line summary of current mission statement}
- **LANDSCAPE.md:** {one-line summary -- key themes, last update indicator}
- **VISION.md:** {one-line summary -- key goals, horizon}
- **MASTER-PLAN.md:** {one-line summary -- current generations, frontier items}

### Recent Activity ({N} commits in window)
- {top 5-8 notable commits or themes}
- SML files modified: {list or "none"}

### Board Snapshot
- Active: {count} items ({brief list})
- Recently completed (display sample): {count} items ({brief list}) — see **Landed-work carry-forward** below for the complete bounded set
- In-flight epics: {count} ({brief list with task counts})

{_carry_summary from step 2d2 goes here verbatim — it is the authoritative
bounded candidate set for landed work eligible for MASTER-PLAN.md reflection,
classified into new / carry-forward / reflected / dismissed buckets}

### Observations
- {any obvious drift between SML and reality}
- {any stale sections noticed}
- {any landed-work bucket imbalance — large carry-forward may indicate
 Strategize has been deferring too much}
```

Immediately after the summary, print a plain-language prompt that makes the available responses obvious without forcing a chooser UI:

```
Does this match reality? Reply in chat:
- **continue** (or "looks good", "accurate", etc.) to proceed to problem framing
- describe any corrections freeform -- I'll fold them into the summary and re-present
- **abort** to stop the strategize session
```

### Handle Operator Response

Interpret the operator's freeform reply:

- **Confirmation** (e.g., "continue", "looks good", "accurate", "ship it"): record the checkpoint outcome as `cp0:confirmed` and proceed to Checkpoint 1.
- **Corrections**: incorporate the operator's feedback into the summary, re-print the updated `## State Refresh Summary` and the prompt, and loop until the operator confirms or aborts. Each correction pass stays conversational -- do not reintroduce a selection chooser. Record the final outcome as `cp0:confirmed` once accepted.
- **Abort** (e.g., "abort", "stop strategize", "cancel"): record `cp0:aborted`, release the STRATEGIZE process work claim (cascades to strategy-file path claims), and stop the entire strategize pipeline:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "strategize_abort",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

If the operator's intent is unclear, ask a single clarifying question in chat rather than guessing.

## Step 4: Checkpoint 1 -- Strategic Problem Framing

Ask the operator what strategic problem or planning question they want to resolve. Use a plain chat/markdown prompt and accept a freeform reply -- do **not** escalate this checkpoint to a harness chooser or selection UI.

Print this prompt inline:

```
## Problem Framing

What strategic question are you looking to resolve in this session? Reply freely in chat.

Examples:
- "The landscape section on X is outdated after we shipped Y"
- "We need to add a new generation to MASTER-PLAN.md for Z"
- "VISION.md doesn't reflect our new direction on Q"
- "General coherence check -- make sure everything is aligned"

If you'd rather stop, reply **abort** and I'll release the claim.
```

### Handle Operator Response

Interpret the operator's freeform reply and capture it as `_problem_framing`:

- **Specific question**: record the framing verbatim and set `_framing_type` = `specific`. This context is passed to subsequent phases.
- **General coherence review** (the operator asks for a broad alignment pass without a specific question): record that intent and set `_framing_type` = `general_coherence`.
- **Abort**: release the STRATEGIZE process work claim (cascades to strategy-file path claims) and stop:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "strategize_abort",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

Then stop the entire strategize pipeline.

If the operator's reply is ambiguous (e.g., a half-formed thought), ask a single clarifying question in chat before committing the framing.

## Step 5: Emit SMLRefreshCompleted

After both checkpoints pass:

```bash
yoke events emit \
 --name "SMLRefreshCompleted" \
 --kind lifecycle \
 --type strategize \
 --source-type skill \
 --severity INFO \
 --outcome completed \
 --project "${_project}" \
 --context "{\"delta_source\":\"${_delta_source}\",\"sml_files_changed\":${_sml_changed_count},\"active_items\":${_active_count},\"problem_framing\":\"${_framing_type}\",\"carry_horizon_days\":${_carry_horizon},\"carry_limit\":${_carry_limit},\"carry_total_pending\":${_carry_total_pending:-0},\"carry_new_this_session\":${_carry_new_count:-0}}"
```

Where:
- `_delta_source` is one of: `event`, `sml_commit`, `default_14d`
- `_sml_changed_count` is the number of SML files modified in the delta window
- `_active_count` is the count of in-flight items (all statuses except idea/done/cancelled/failed/stopped)
- `_framing_type` is one of: `specific`, `general_coherence`
- `_carry_horizon` / `_carry_limit` come from step 2d2's config reads
- `_carry_total_pending` / `_carry_new_count` are extracted immediately after
 `_carry_json` is built in step 2d2, so SMLRefreshCompleted carries explicit
 provenance of the bounded candidate set that the session actually saw

## Output Context

This phase produces the following inline context for subsequent phases:

- `## State Refresh Summary` -- the confirmed summary from Checkpoint 0
- `## Problem Framing` -- the operator's strategic question from Checkpoint 1
- Delta window bounds for scoping the research phase
