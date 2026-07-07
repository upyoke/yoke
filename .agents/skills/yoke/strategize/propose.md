# Propose

Draft minimal SML changes based on the operator's normative filter results from the research phase. Present batched changes for operator approval and emit the SMLChangeProposed event.

## Prerequisites

This phase receives inline context from the research phase (research.md):

- `## Landscape Analysis` -- full compiled findings
- `## Operator Filter Results` -- operator-approved subset of findings with facts, interpretations, and proposed actions

## Step 1: Draft SML Changes

For each selected finding from the Operator Filter Results, draft the minimal change needed to resolve it. Changes are section-level edits, not full file rewrites.

### 1a. MISSION.md Handling

**MISSION.md is stable by default.** Do not draft changes to MISSION.md unless at least one of the following is true:

- The operator explicitly requested a mission change in their Problem Framing
- A contradiction finding specifically identifies a MISSION.md issue AND the operator selected it in the normative filter
- The selected findings imply a strategic shift whose nature or scope no longer fits the current mission statement

When the third case applies, keep the mission edit minimal and clearly justify why the strategic shift rises to mission level instead of living only in LANDSCAPE.md, VISION.md, or MASTER-PLAN.md.

If a finding suggests possible mission drift but the case for a mission change is still weak or ambiguous, flag it instead of drafting a change:

```
Note: Finding #{N} may imply MISSION.md drift. Draft a mission change only if the
strategic shift is large enough that the current mission statement no longer fits.
Otherwise, carry the update in LANDSCAPE.md, VISION.md, or MASTER-PLAN.md and flag
MISSION.md for operator review.
```

### 1b. Change Drafting Rules

For each change:

- **Minimal diff:** Change only the specific section or paragraph that needs updating. Do not rewrite surrounding content.
- **Preserve voice and structure:** Match the existing file's tone, formatting, and organizational patterns.
- **One finding = one change:** Each finding produces exactly one change entry (or zero if the finding requires no SML edit).
- **Section-level granularity:** Identify changes by file and section header, not by line number (sections are more stable references).

### 1b0. Future-Concept Pull-Forward Rules

When an approved finding says current work has pulled a later-generation concept forward, draft the SML change so the plan treats the current surface as the first version of the end-state primitive. Do not leave the later generation describing the underlying machinery as wholly future. The later generation may still own broader UX, fan-out, authority depth, policy surface, or scale-out behavior, but the primitive itself is now current.

When an approved finding says a planned surface looks temporary, draft one of two shapes:

- **Pull forward / consume existing primitive:** Name the existing or current-slice primitive (`path_claims`, `coordination_leases`, events ledger, actors, phase runs, execution journal, compiled packet, etc.) and make the ticket consume it.
- **Declare deletion target:** If the surface is intentionally temporary, require the ticket to name the exact later slice or primitive that deletes or absorbs it.

Avoid changes that merely move a phrase from one generation to another without changing the implementation instruction. The output should tell the next ticket author what to build, what not to build yet, and what future surface consumes the v0.

### 1b1. LANDSCAPE.md Editorial Rules

`LANDSCAPE.md` is explicitly a legibility artifact, not an append-only release-notes feed. When drafting changes that land in `LANDSCAPE.md` — whether they come from factual drift, missing context, or the LANDSCAPE Editorial Pressure findings from the research phase — apply these additional drafting rules on top of the minimal-diff principle above:

- **Weave first, add second.** A new signal should be woven into the existing paragraph or bullet about the same theme, competitor, or capability. A net-new bullet or paragraph is the fallback, not the default. If a related section already exists, the first draft attempt must rewrite that section; only escalate to an additional bullet if the existing prose genuinely cannot absorb the update.
- **Rewrite when the theme is the same.** When a new development sharpens, updates, narrows, or contradicts the same strategic theme an existing paragraph already covers, rewrite that paragraph instead of appending a fresh bullet beside it. A slightly larger rewrite of one section is preferable to multiple tiny append-only additions when the goal is to keep the file legible.
- **Summarize, don't enumerate.** When several recent developments point at the same theme (same actor, same shift, same capability class), combine them into one synthesized update. Do not produce one bullet per development. Repeated small movements become a higher-level statement that preserves the insight without preserving the list.
- **Consolidate before adding when a section is already dense.** If the research phase flagged a section as overgrown, dense, or duplicated, the first change for that section must be a consolidation pass (merge, retire, or rewrite to a sharper synthesis). Only after consolidation should any net-new content be proposed, and only if the consolidated section still has room for it.
- **Retire stale and table-stakes observations.** When rewriting a section, actively drop entries that have become stale, superseded, or baseline industry behavior. Retirement is a valid change type for LANDSCAPE.md — a change whose Proposed content is "(remove)" or "(folded into paragraph X)" is not a failure of drafting, it is editorial discipline.
- **Justify every net-new bullet or paragraph.** Any change whose Type is `add` against `LANDSCAPE.md` must carry an explicit justification in the Rationale field explaining why the signal could not be woven into an existing section and why a new bullet or paragraph is the clearest strategic shape. "The finding said to add it" is not a justification. If the justification is weak, convert the change to a rewrite of an adjacent section.
- **Preserve legitimate new signal.** Editorial discipline is a filter on shape, not on substance. Do not drop real new signal just because the section is already long — instead, weave, consolidate, or retire adjacent content to make room for the sharper synthesis.

When a LANDSCAPE.md change applies one of these rules, record it explicitly in the change entry's Rationale field so the approval checkpoint can see the editorial move (e.g., "woven into existing paragraph X", "consolidated three bullets into one", "retired table-stakes observation").

### 1c. Change Entry Format

For each proposed change, produce:

```
### Change {N}: {SML file} > {section}
**Finding:** #{finding_number} -- {brief description}
**Type:** update | add | remove | consolidate | retire
**File:** {LANDSCAPE.md | VISION.md | MASTER-PLAN.md}
**Section:** {section header path, e.g., "## Current Landscape > ### Infrastructure"}

**Current content (abbreviated):**
> {relevant excerpt of what is there now, max 5 lines}

**Proposed content:**
> {the replacement text for this section; for retire/consolidate, this may be "(removed)" or "(folded into paragraph X)"}

**Rationale:** {why this change, referencing the evidence from the finding; for LANDSCAPE.md adds, include explicit justification for why the signal could not be woven}
```

The `consolidate` and `retire` types are first-class editorial moves for `LANDSCAPE.md` (and any other SML file whose legibility is threatened by accumulation). Do not collapse them into `remove` — the distinction matters for the approval checkpoint, which reads the change type to understand the editorial intent.

### 1d. Group Changes by File

After drafting all individual changes, group them by target file:

```
## Proposed SML Changes

### LANDSCAPE.md ({N} changes: {A} weave/update, {B} consolidate, {C} retire, {D} add)
{list of changes targeting LANDSCAPE.md; each change notes its editorial move in the Rationale}

### VISION.md ({N} changes)
{list of changes targeting VISION.md}

### MASTER-PLAN.md ({N} changes)
{list of changes targeting MASTER-PLAN.md}

### MISSION.md (stable by default)
{any flagged implications, or "No changes -- MISSION.md remains unchanged for this session."}
```

The LANDSCAPE.md header line explicitly counts weave/update, consolidate, retire, and add moves so the operator and the approval checkpoint can see the editorial shape of the proposed batch at a glance. If `D` (add) dominates the batch for a section that the research phase flagged as already dense, revisit the LANDSCAPE.md Editorial Rules before presenting — the batch may still be defaulting to append-only shape instead of weaving or consolidating.

## Step 2: Checkpoint 3 -- SML Change Approval

Present the batched changes to the operator for approval. This is the gate before any SML files are modified.

### Presentation

Show the grouped changes with a summary header:

```
## Proposed SML Changes ({N} total across {M} files)

{grouped changes from Step 1d}

### Summary
- LANDSCAPE.md: {N} changes
- VISION.md: {N} changes
- MASTER-PLAN.md: {N} changes
- MISSION.md: stable by default ({N} changes or flagged implications)

Reply in chat:

- **approve** (or "ship it", "apply all") to apply every change as drafted
- describe revisions freeform (which changes to modify, drop, or adjust) and I'll re-draft only the affected entries
- **defer** to record all changes for the next strategize session without applying them
- **abort** to stop without applying any changes
```

Print the grouped changes and the prompt above as ordinary chat/markdown output. Do **not** escalate this checkpoint to a harness chooser or selection UI -- the batched diff is too long-form for one and revision handling must stay conversational so the operator can call out specific entries.

### Handle Operator Response

Interpret the operator's freeform reply:

- **Approve all** (e.g., "approve", "ship it", "apply everything"): mark all changes as approved and carry them forward to the frontier-implication check. Record the checkpoint outcome as `cp3:approved_all`.
- **Revise specific changes**: incorporate the operator's revisions. Re-draft affected changes in chat and re-present **only** the revised ones for confirmation (do not re-present unchanged items), then loop until the operator confirms or picks another branch. Once the revisions settle, record the outcome as `cp3:approved_revised`.
- **Defer all** (e.g., "defer", "not now", "hold these for next time"): record all changes as deferred in the approval status and skip to event emission. Record the outcome as `cp3:deferred_all`.
- **Abort**: release the STRATEGIZE process work claim and stop the entire strategize pipeline:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "strategize_abort",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

## Step 3: Record Approval Status

```
## Approval Status

**Decision:** approved | revised | deferred | aborted
**Changes approved:** {count}
**Changes deferred:** {count}
**Changes dropped:** {count}

### Approved Changes
{numbered list of approved changes with file and section}

### Deferred Changes (if any)
{numbered list of deferred changes for future sessions}
```

## Step 4: Emit SMLChangeProposed Event

After the operator checkpoint completes (regardless of approval outcome), emit the event:

```bash
yoke events emit \
 --name "SMLChangeProposed" \
 --kind lifecycle \
 --type strategize \
 --source-type skill \
 --severity INFO \
 --outcome completed \
 --project "${_project}" \
 --context "{\"total_changes\":${_total_changes},\"approved\":${_approved_count},\"deferred\":${_deferred_count},\"dropped\":${_dropped_count},\"files_affected\":[${_files_list}],\"mission_readonly\":true}"
```

Where:
- `_total_changes` is the total number of changes drafted
- `_approved_count` is the number approved by the operator
- `_deferred_count` is the number deferred to a future session
- `_dropped_count` is the number dropped during revision
- `_files_list` is a JSON array of affected file names (e.g., `"LANDSCAPE.md","VISION.md"`)
- `mission_readonly` is true unless the operator explicitly requested MISSION.md changes

## Output Context

This phase produces the following inline context for subsequent phases:

- `## Proposed SML Changes` -- the full set of drafted changes grouped by file
- `## Approval Status` -- the operator's approval decisions
- These feed into the frontier-implication check (approve.md) and the write-out step (finalize.md) for writing approved changes
