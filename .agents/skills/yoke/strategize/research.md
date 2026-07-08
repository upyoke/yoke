# Research

Perform landscape analysis and normative filtering based on the State Refresh Summary and Problem Framing from the state-refresh phase. This phase identifies factual drift, missing context, and contradictions in the SML, then asks the operator which findings matter.

## Prerequisites

This phase receives inline context from the state-refresh phase (refresh.md):

- `## State Refresh Summary` -- confirmed summary of current SML state and recent activity
- `## Problem Framing` -- the operator's strategic question or "general coherence review"
- Delta window bounds for scoping analysis

## Step 1: Landscape Analysis

Analyze the SML files against the confirmed state refresh to identify discrepancies. Work through each SML file systematically.

### 1a. Factual Drift

Compare each SML file's claims against the confirmed recent reality from the State Refresh Summary. Look for:

- **Completed work not reflected:** Items marked done or passed whose outcomes are not captured in LANDSCAPE.md or MASTER-PLAN.md
- **Stale timelines or milestones:** Dates, generation boundaries, or phase markers that no longer match reality
- **Outdated competitive or environmental claims in LANDSCAPE.md:** Statements about the landscape that may have shifted based on recent work or external changes
- **MASTER-PLAN.md frontier drift:** Items listed as frontier that are already done, or newly unblocked items not yet recognized as frontier

For each drift point found, record:
- Which SML file and section
- What it currently says
- What reality appears to be (based on refresh data)
- Confidence level: high (clear factual mismatch) or medium (interpretation needed)

### 1a1. MASTER-PLAN Frontier Order + Prerequisite Validation

Beyond narrative drift review, run the deterministic MASTER-PLAN validator. It extracts the ordered frontier entries from `MASTER-PLAN.md` and the prerequisite/enabling prose relationships around them, then cross-checks both against live item statuses.

```bash
yoke strategy master-plan-check
```

Read the output and fold it into the rest of the landscape analysis:

- **Contradictions section:** Each row is a concrete ordered-frontier or prerequisite-prose contradiction with `earlier`, `earlier_status`, `later`, `later_status`, and a rationale. Carry every contradiction into the factual-drift findings table (Step 2) — each one becomes a finding with confidence `high` (the live statuses are DB truth).
- **Ambiguous prerequisite prose:** Sentences with three or more `YOK-N` refs that also contain prerequisite keywords. Surface these as medium-confidence advisory findings — the validator deliberately does not infer a specific pair when the prose is too dense. Ask the operator at Checkpoint 2 whether any of them matter.
- **Advisories:** Missing `Backlog By Generation` section, exceptional-status items (`blocked`, `cancelled`, etc.), or items with no live row — include them as soft notes in the "Missing Context" or "Factual Drift" tables rather than treating them as contradictions.

If the validator prints `No concrete frontier or prerequisite-prose contradictions detected`, the plan is coherent with live state on those two specific axes — still scan narratively for the other drift categories above.

The validator is read-only and never mutates the plan. It reads the local rendered view at `.yoke/strategy/MASTER-PLAN.md` (a gitignored cache of the DB row); if `HC-strategy-render-staleness` has flagged stale views, run `yoke strategy render --target-root "$REPO_ROOT"` first so the validator sees the DB authority's current content. Any edits to `MASTER-PLAN.md` still flow through the propose and approve phases as with any other SML change.

### 1b. Missing Context

Identify important recent developments that have no SML representation at all:

- New capabilities or patterns that landed but are not mentioned in LANDSCAPE.md
- Strategic shifts implied by recent work that VISION.md does not acknowledge
- Completed generations or milestones that MASTER-PLAN.md does not mark as done
- New dependencies or constraints discovered during recent work

### 1b1. Future-Concept Pull-Forward Drift

Apply the `MASTER-PLAN.md` future-concept pull-forward principle while reading the plan. Generation boundaries are sequencing aids, not architecture boundaries. Look for current or recently-landed work that already creates machinery the plan names in later generations: `actor_id`, `session_id`, `heartbeat_at`, ownership, leases, claims, approvals, overrides, evidence, run records, execution journals, compiled packets, route-around facts, resource locks, and shared-state coordination.

Flag both directions:

- **Pulled-forward concept not reflected:** landed or current work is an end-state v0 of a later-generation concept, but the SML still describes that concept as wholly future or treats the current surface as temporary.
- **Temporary local workaround risk:** planned work adds a local lock, progress note, event, run record, approval, override, or ownership surface without explaining whether it is the smallest v0 of the end-state primitive or naming its deletion / absorption target.

For each finding, record the current slice, the later-generation concept it touches, whether the right move is **pull forward**, **consume existing primitive**, or **declare deletion target**, and the concrete SML section that must change.

### 1c. Contradictions

Look for internal inconsistencies across SML files:

- VISION.md goals that conflict with MASTER-PLAN.md priorities
- LANDSCAPE.md claims that contradict recent board state
- MASTER-PLAN.md generation definitions that overlap or have gaps
- Any SML content that conflicts with MISSION.md (the hardest constraint)

### 1d. Problem-Scoped Analysis

If the operator provided a specific strategic question in Problem Framing, focus additional analysis on that topic:

- Trace the specific question through each SML file
- Identify which sections are most relevant to the question
- Note any gaps where the SML is silent on the operator's concern

If the operator chose "general coherence review," skip this step (the full analysis above covers it).

### 1e. LANDSCAPE Editorial Pressure

`LANDSCAPE.md` is meant to be "gathered and kept legible" — a compact strategic synthesis, not an append-only release-notes feed. Research must treat section growth and density as first-class review dimensions, not just factual correctness, so later phases do not default to appending another bullet.

Run this pass against `LANDSCAPE.md` alongside the drift analysis above. Flag anything that pulls the file toward accumulation instead of synthesis:

- **Overgrown or dense sections.** Sections that have grown to the point where a reader has to scan many bullets to extract the strategic point. Candidate signal: lots of sibling bullets covering the same theme, long lists with no synthesis sentence, or a section that now occupies a disproportionate share of the file relative to its strategic weight.
- **Duplicated or near-duplicate observations.** Two or more bullets or paragraphs saying essentially the same thing about the same actor, capability, or trend. These should be merged into one sharper statement.
- **Table-stakes observations.** Items that were once a differentiator or signal but are now baseline industry behavior. These no longer need their own entry — retire them or fold them into a single "now table stakes" sentence.
- **Stale or superseded observations.** Entries that newer developments have made inaccurate, narrower, or obsolete. Retire or rewrite them instead of letting the new development sit beside the old claim.
- **Related recent developments that should be summarized.** When several new signals point at the same strategic theme (same competitor, same shift, same capability class), weave them into one synthesized update rather than adding one bullet per development. Summarize-don't-enumerate is the default for grouped recent activity.

For each editorial-pressure finding, record:

- Which `LANDSCAPE.md` section
- What the current content looks like (brief excerpt or bullet count)
- The proposed editorial move: **weave**, **consolidate**, **retire**, **summarize**, or **rewrite**
- A one-line rationale explaining why that move keeps the file legible

Editorial-pressure findings carry forward into the propose phase alongside factual drift and missing context. They are explicitly not limited to "the file is factually wrong" — a section that is factually correct but too dense to stay legible is still a valid finding.

If the operator's Problem Framing is a specific strategic question rather than a general coherence review, still run this pass — editorial pressure in unrelated sections can be noted briefly, but the bulk of the pass should focus on the sections touched by the question.

## Step 2: Compile Findings

Organize all findings into a structured format that cleanly separates facts from interpretations.

### Findings Format

```
## Landscape Analysis

### Factual Drift
| # | SML File | Section | Current Claim | Observed Reality | Confidence |
|---|----------|---------|---------------|------------------|------------|
| 1 | {file} | {sect} | {what it says}| {what is true} | high/med |
| ...

### Missing Context
| # | Topic | Relevant SML File(s) | What Is Missing |
|---|-------|----------------------|-----------------|
| 1 | {topic} | {files} | {description} |
| ...

### Future-Concept Pull-Forward
| # | Current Surface | Later Concept | Required Move | SML Change |
|---|-----------------|---------------|---------------|------------|
| 1 | {surface/ticket} | {concept} | pull forward / consume existing primitive / declare deletion target | {file + section} |
| ...

### Contradictions
| # | Files Involved | Description |
|---|----------------|-------------|
| 1 | {file A} vs {file B} | {what conflicts} |
| ...

### LANDSCAPE Editorial Pressure
| # | Section | Current Shape | Editorial Move | Rationale |
|---|---------|---------------|----------------|-----------|
| 1 | {section} | {bullet count / dense paragraph / duplicate / table-stakes / stale} | weave / consolidate / retire / summarize / rewrite | {why this keeps the file legible} |
| ...

### Problem-Specific Findings (if applicable)
- {findings related to operator's specific question}
```

Count the total findings and categorize them.

## Step 3: Checkpoint 2 -- Normative Filter

Present the compiled findings to the operator. The key purpose of this checkpoint is to separate objective observations from normative decisions about what to do about them.

### Presentation Format

Present findings grouped by category (factual drift, missing context, future-concept pull-forward, contradictions). For each finding, clearly label:

- **Fact:** The objective observation (what the SML says vs what reality shows)
- **Interpretation:** What this might mean for strategy (your analysis)
- **Proposed Action:** What could be done about it (add/update/remove SML content)

```
## Research Findings ({N} total)

### Factual Drift ({N} items)

**Finding 1:** {SML file} > {section}
- Fact: {objective observation}
- Interpretation: {what this means}
- Proposed action: Update {file} section "{section}" to reflect {reality}

{... repeat for each finding ...}

### Missing Context ({N} items)
{... same format ...}

### Future-Concept Pull-Forward ({N} items)
{... same format, with Required Move naming pull forward / consume existing primitive / declare deletion target ...}

### Contradictions ({N} items)
{... same format ...}

Which findings matter for this session? Reply in chat:

- "all" to carry every finding forward
- a freeform selection (by number, category, or description) to narrow the set
- a reframe -- describe what the analysis missed and I'll rerun with the new focus
- **abort** to stop strategize
```

Print the findings and the prompt above as ordinary chat/markdown output. Do **not** escalate this checkpoint to a harness chooser or selection UI -- the analysis is too long-form for one and selection handling must stay conversational.

### Handle Operator Response

Interpret the operator's freeform reply:

- **Take everything** (e.g., "all", "keep them all", "everything matters"): carry all findings forward to the propose phase. Record the checkpoint outcome as `cp2:all`.
- **Specific selection** (numbers, categories, or descriptive callouts): record the selected subset as `_operator_filter_results`. Confirm the selection back in chat if it is ambiguous, then carry only the selected findings forward. Record the outcome as `cp2:filtered_{kept}_of_{total}` using the semantic filtered-count label.
- **Reframe** (e.g., "none of these matter", "you're looking in the wrong place"): ask a single clarifying question in chat if needed, then redo the analysis with the new focus -- return to the problem-scoped analysis step with the updated framing and re-enter this checkpoint when the new findings are ready. Record the outcome for the retried round only; the earlier reframed round is superseded.
- **Abort**: release the STRATEGIZE process work claim (which cascades to the strategy-file path claims) and stop the entire strategize pipeline:

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "strategize_abort",
  "payload": {"claim_id": <claim_id>, "reason": "released"}
}
```

Record the operator's filter decisions as `_operator_filter_results`.

## Step 4: Record Filtered Results

Compile the operator-approved findings into the output context for the propose phase.

```
## Operator Filter Results

**Findings selected:** {count} of {total}
**Categories included:** {list}

### Selected Findings
{numbered list of findings the operator approved, each with its fact/interpretation/proposed-action}
```

## Output Context

This phase produces the following inline context for subsequent phases:

- `## Landscape Analysis` -- the full compiled findings from Step 2
- `## Operator Filter Results` -- the operator-filtered subset from Step 4
- These feed directly into the propose phase (propose.md) for SML change drafting
