# Shepherd: Boss Verdict Parsing, Persistence, Reflections, and Caveat Triage

Covers steps 5f–5i: the 5-layer verdict parsing chain, verdict persistence, reflection capture, and the caveat resolution gate.

**Inherited from router/boss-verdict.md:** `_num`, `_transition`, `_attempt`, `_session_id`, `_worker_name`, `_boss_raw_output`, `_pre_boss_verdict_max_id`, `_db_boss_row_id`.

---

## 5f. Parse Boss Verdict

The verdict parsing chain applies layers in order, stopping at the first successful extraction.

Initialize `_verdict_source=""` and `_db_boss_row_id=""` before the layer chain.

**Layer 1: Primary strict regex** (existing).
Search for a line matching `^VERDICT:\s*(READY|NOT_READY|CAVEATS)\s*$` (case-sensitive). If found, extract the verdict.

**Layer 2: DB fallback query** (existing).
If Layer 1 fails, check whether the Boss persisted its verdict to the DB directly:
```bash
_db_boss_row=$(yoke db read --format lines "SELECT id, verdict, COALESCE(caveats,'') FROM shepherd_verdicts WHERE item='YOK-$_num' AND transition='$_transition' AND worker='$_worker_name' AND id > $_pre_boss_verdict_max_id ORDER BY id DESC LIMIT 1")
_db_boss_row_id=$(printf '%s' "$_db_boss_row" | cut -d'|' -f1)
_db_boss_verdict=$(printf '%s' "$_db_boss_row" | cut -d'|' -f2)
_db_boss_caveats=$(printf '%s' "$_db_boss_row" | cut -d'|' -f3-)
```
If `_db_boss_verdict` is `READY`, `NOT_READY`, or `CAVEATS`, use it as `_verdict` and `_db_boss_caveats` for `_caveats_text`. The `id > _pre_boss_verdict_max_id` anchor prevents stale rows from prior retries from matching.

**Layer 3: Fallback regex parser** (NEW).
If Layers 1-2 fail, apply broader case-insensitive patterns to extract the verdict from natural language. Search the Boss's full text output for these patterns:
- `verdict:\s*(ready|not_ready|not ready|caveats)` anywhere on a line (case-insensitive, not anchored to line start)
- `verdict is\s+(ready|not_ready|not ready|caveats)` (case-insensitive)
- `recommend(?:ing)?\s+(ready|not_ready|not ready|caveats)` (case-insensitive)
- `issuing\s+(ready|not_ready|not ready|caveats)` (case-insensitive)
- Bare `NOT_READY` or `CAVEATS` or `READY` appearing as a standalone token (word boundaries) in the **last 20 lines** of output (recency-weighted, since verdicts typically appear near the end)

Normalization: `not ready` maps to `NOT_READY`, case-insensitive `ready` maps to `READY`, etc.

**Conflict resolution:** If multiple conflicting verdicts are found, prefer the one closest to the end of the output.

If extracted via Layer 3, log: `"Verdict extracted via fallback_regex (primary parser failed)"`. Prepend `[FALLBACK_PARSED]` to `_caveats_text`. This marker does NOT trigger model escalation (unlike `[UNPARSEABLE_BOSS_OUTPUT]`).

**Layer 4: Lightweight verdict extraction prompt** (NEW).
If Layer 3 also fails, invoke a lightweight single-shot subagent to parse the Boss's raw output:

**Dispatch:** descriptor `DispatchDescriptor(role="boss", extras=(("model","haiku"),))` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Single-shot extraction (`maxTurns: 1` enforced by the parent skill, not the descriptor). Result-schema markers: `VERDICT: READY|NOT_READY|CAVEATS`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Extract the verdict from the following Boss review output.
 Return exactly one line: VERDICT: READY, VERDICT: NOT_READY, or VERDICT: CAVEATS.
 If you cannot determine the verdict, return: VERDICT: INDETERMINATE.
 Do not explain. Do not use tools. Just return the verdict line.

 Boss output:
 {_boss_raw_output}
```

Parse the extraction output with the same strict regex as Layer 1. `INDETERMINATE` is treated as a parse failure (falls through to Layer 5).

If extracted via Layer 4, log: `"Verdict extracted via lightweight_extraction (primary parser failed)"`. Prepend `[FALLBACK_PARSED]` to `_caveats_text`.

**Layer 5: Store UNPARSEABLE and continue to retry handling.**
If all layers fail:
- Set `_verdict="NOT_READY"` (deterministic safety default)
- Set `_caveats_text="[UNPARSEABLE_BOSS_OUTPUT] Boss returned no parseable VERDICT block. All fallback layers (strict regex, DB query, fallback regex, lightweight extraction) failed."`
- Continue through retry handling. This marker is used for model escalation on subsequent Boss retries.

**Caveats extraction for fallback-parsed verdicts:**
When Layer 3 or Layer 4 identifies a CAVEATS verdict: look for numbered lists in the Boss output following the verdict indicator. If Layer 4 was used and none found, re-prompt: "Also extract the caveats list." If still not extractable, persist with `_caveats_text="[FALLBACK_PARSED] [Caveats not extractable -- review Boss output manually]"` and include full Boss output in `_boss_feedback`.

**Model escalation threshold:**
The existing model escalation logic in step 5e counts `[UNPARSEABLE_BOSS_OUTPUT]` markers. With the new fallback layers, the threshold remains at 2, but only counts genuine `[UNPARSEABLE_BOSS_OUTPUT]` (i.e., all fallbacks failed). `[FALLBACK_PARSED]` verdicts do NOT increment the escalation counter.

**Constrained retry prompt:**
When a retry is triggered after all fallback layers failed (Layer 5), the retry prompt for the full Boss agent must include this constraint: "Read the authoritative artifact from the DB using the same scope-aware source selection as the main review (`spec`/`prd` -> `items.spec`, falling back to `items.body` (virtual rendered field); `plan` -> `items.technical_plan` + `items.worktree_plan`, with `items.spec`/`items.design_spec` for context and `items.body` only as fallback when a structured field is empty), but do NOT explore the broader codebase. Your FIRST output line must be the VERDICT: block." This prevents the Boss from repeating the same codebase-exploration pattern that caused the original turn budget exhaustion while still allowing it to read the authoritative artifact.

Also extract `_boss_feedback` -- the full Boss reasoning -- for potential retry prompts.

---

## 5g. Persist Verdict

**Populate `_caveats_text` for all verdict types** before persisting:

| Verdict | `_caveats_text` value |
|---|---|
| CAVEATS | Numbered caveat list from Boss output (existing behavior) |
| NOT_READY | Boss feedback/reasoning (`_boss_feedback`) |
| BLOCKED | Blocking reason |
| READY | Empty string (existing behavior) |

**Dedup guard:** If the verdict was extracted via Layer 2 (DB fallback — meaning the Boss self-persisted despite being told not to during this invocation), skip the insert and reuse the anchored row ID to avoid duplicates:

```bash
if [ "$_verdict_source" = "layer2_db" ] && [ -n "$_db_boss_row_id" ]; then
 # Boss already persisted during this invocation — reuse the anchored row ID.
 _verdict_id="$_db_boss_row_id"
 echo "Verdict already persisted by Boss during this invocation (Layer 2 recovery) — reusing row $_verdict_id"
else
 _verdict_id=$(yoke shepherd verdict --item "YOK-$_num" --transition "$_transition" --worker "$_worker_name" --verdict "$_verdict" --caveats "$_caveats_text")
fi
```

Set `_verdict_source` during the parsing chain in step 5f:
- Layer 1 (strict regex): `_verdict_source="layer1_regex"`
- Layer 2 (DB fallback): `_verdict_source="layer2_db"`
- Layer 3 (fallback regex): `_verdict_source="layer3_fallback"`
- Layer 4 (lightweight extraction): `_verdict_source="layer4_extraction"`
- Layer 5 (unparseable): `_verdict_source="layer5_unparseable"`

Where:
- `_worker_name` is the worker that produced the artifact (PM, Designer, Architect, or "review" for planning_to_plan_drafted)
- `_session_id` is the session ID (from `--session` arg, or empty in standalone mode)
- `_db_boss_row_id` is the Layer 2 row ID captured from rows created after `_pre_boss_verdict_max_id`
- `_verdict_id` is the row ID of the newly inserted verdict row (or reused row for Layer 2), used when persisting caveat dispositions in step 5i

---

## 5h. Capture Reflections

Search the worker's and Boss's responses for reflection blocks:

```
---REFLECTION-START---
---BEGIN ENTRY---
timestamp: {ISO}
agent: {name}
context: {context}
category: {category}
{observation text}
---END ENTRY---
---REFLECTION-END---
```

For each extracted entry, persist via:
```bash
yoke ouroboros entry insert \
 --agent "{agent}" \
 --context "shepherd YOK-$_num $_transition" \
 --category "{category}" \
 --observation "{observation}"
```

---

## 5i. Caveat Resolution Gate

When the verdict is **CAVEATS**, every caveat must be triaged before the pipeline advances. No caveat may be left undispositioned.

**For each caveat in `_caveats_text`:**

1. **Can this be resolved now by editing the artifact?** Determine whether the caveat points to something fixable within the current transition's scope -- a missing detail in the spec, an ambiguity in the plan, an unresolved open question, a gap the Boss flagged that the worker should have covered. If so:
 - Fix it. Edit the relevant DB-backed artifact directly (for example `spec`, `design_spec`, `technical_plan`, `worktree_plan`, or task content) to address the concern.
 - **The `resolution_details` MUST reference the specific change** -- section name, field modified, or content added/removed. Vague summaries like "already handles this", "determined not needed", or "Architect confirmed no changes required" are NOT valid RESOLVED details. If you cannot point to a specific artifact edit you just made, the disposition is ANALYZED, not RESOLVED.
 - Record the disposition: `RESOLVED: {one-line summary of what was changed, referencing the specific edit}`

2. **Is this an implementation concern for a later stage?** If the caveat is about how something should be built, tested, or deployed -- something the current worker cannot act on -- then it must be **persisted in the ticket artifacts** so the engineer or next worker sees it when they read the item:
 - Write the caveat into the `shepherd_caveats` structured field (rendered back into the item body under `## Shepherd Caveats`; see format below).
 - If tasks exist (post-planning transitions) and the caveat explicitly references a task number (e.g., "Task 005: ..."), also write it into that task's body.
 - Record the disposition: `DEFERRED to YOK-{N} body: {caveat summary}`

3. **Does analysis show no change is needed?** If the caveat is based on a misunderstanding, or the concern is already addressed elsewhere in the artifact, or analysis genuinely determines the caveat is inapplicable, record as ANALYZED. **ANALYZED caveats MUST be persisted to `shepherd_caveats`** (rendered under `## Shepherd Caveats`) so a human reviewer can verify the judgment -- they cannot silently disappear into the DB.
 - Write the caveat and its reasoning into `shepherd_caveats` under `## Shepherd Caveats > ### {_transition}`.
 - Record the disposition: `ANALYZED: {reasoning why no change needed}`

**Persist each caveat disposition.** After triaging each caveat, persist the disposition to the DB:

```bash
yoke shepherd caveat-disposition \
 --item "YOK-$_num" --transition "$_transition" --attempt "$_attempt" \
 --caveat-num "$_caveat_num" --caveat-text "$_caveat_text" \
 --disposition "$_disposition" --resolution-details "$_resolution_details" \
 --verdict-id "$_verdict_id"
```

Where:
- `_caveat_num` is the 1-based index of the caveat in the list
- `_caveat_text` is the text of the individual caveat
- `_disposition` is `RESOLVED`, `DEFERRED`, or `ANALYZED`
- `_resolution_details` is a one-line summary (what was changed for RESOLVED, where it was deferred to for DEFERRED, or reasoning for ANALYZED)
- `_verdict_id` is the row ID captured in step 5g

**Build `_caveats_list` during triage.** For each DEFERRED or ANALYZED caveat, append a formatted line to `_caveats_list`. RESOLVED caveats are NOT written to the body (they were fixed in-place). Format:

```bash
_caveats_list=""
# After triaging each caveat (inside the loop):
if [ "$_disposition" = "DEFERRED" ] || [ "$_disposition" = "ANALYZED" ]; then
 _caveats_list="${_caveats_list}
- **Caveat ${_caveat_num}:** ${_caveat_text} — *${_disposition}:* ${_resolution_details}"
fi
```

Do NOT write caveats to the body individually during triage — the template below writes them all at once after the loop completes.

**Disposition log.** After triaging all caveats, output the full list:

```
Caveat triage for YOK-{N} at {_transition}:
 1. RESOLVED: {summary} -- {specific artifact edit made}
 2. DEFERRED to YOK-{N} body: {summary}
 3. ANALYZED: {summary} -- {reasoning why no change needed}
```

**Body format for DEFERRED and ANALYZED caveats.** Write to `items.shepherd_caveats` via structured field writes. ANALYZED caveats are persisted so human reviewers can verify the shepherd's reasoning.

```bash
# Build subsection; use awk (not sed) to avoid BSD sed failures with markdown
# metacharacters like **bold**, [links](url), |pipes|.
_new_subsection=$(printf '### %s\n\n%s\n' "$_transition" "$_caveats_list")
_existing_caveats=$(yoke items get $_num shepherd_caveats 2>/dev/null)

if [ -n "$_existing_caveats" ]; then
 _has_transition=$(printf '%s\n' "$_existing_caveats" | grep -c "^### ${_transition}$" || true)
 if [ "$_has_transition" -gt 0 ]; then
 # RETRY CASE: replace existing ### {_transition} subsection
 _before=$(printf '%s\n' "$_existing_caveats" | awk -v h="### $_transition" '$0 == h { exit } { print }')
 _after_section=$(printf '%s\n' "$_existing_caveats" | awk -v h="### $_transition" '
 found == 1 && /^### / { past=1 }
 past == 1 { print }
 $0 == h { found=1 }
 ')
 _merged_caveats="${_before}${_new_subsection}"
 if [ -n "$_after_section" ]; then
 _merged_caveats="${_merged_caveats}
${_after_section}"
 fi
 else
 # NEW TRANSITION: append new subsection
 _merged_caveats="${_existing_caveats}

${_new_subsection}"
 fi
else
 _merged_caveats="$_new_subsection"
fi

# Guard: non-empty check before write
if [ -z "$_merged_caveats" ]; then
 echo "Error: Caveats merge produced empty output — aborting DB write to prevent data loss." >&2
fi
```

When `_merged_caveats` is non-empty, dispatch the
`items.structured_field.replace` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md))
with `target = {kind: "item", item_id: $_num}` and `payload =
{field: "shepherd_caveats", content: "$_merged_caveats", source:
"shepherd"}`. Three cases handled: **(1) No existing content** —
creates a single `### {_transition}` subsection. **(2) New
transition** — preserves prior subsections, appends new one.
**(3) Same transition (retry)** — replaces only the matching
subsection.

**Mode differences:**
- **Standalone mode:** The shepherd may ask the user for guidance on ambiguous caveats (resolve vs. defer).
- **Subagent mode:** Triage autonomously. Default to DEFERRED when uncertain -- over-communicating to the next worker is safer than silently assuming something is resolved. Use ANALYZED only when the reasoning is clear and defensible; when in doubt, prefer DEFERRED.

**Atomicity.** Structured field writes are atomic -- they cannot corrupt other fields. The body is re-rendered from all fields by the internal body renderer.
