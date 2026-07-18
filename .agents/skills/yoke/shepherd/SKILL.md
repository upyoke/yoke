---
name: shepherd
description: "Advance an epic from refined-idea to plan-drafted through quality-gated transitions"
argument-hint: "{YOK-N}"
---

# /yoke shepherd {YOK-N}

Shepherd an epic through the pipeline from `refined-idea` to `plan-drafted`, applying Boss quality gates at every transition. Each step is: Worker produces artifact -> Boss reviews -> persist verdict -> advance or retry.

Shepherd is **epic-only**. Issues route through `/yoke refine` (idea → refined-idea) and `/yoke advance` (refined-idea → implementing). The `idea` → `refined-idea` transition is handled by `/yoke refine`, not shepherd.

> Standalone mode (`/yoke shepherd YOK-N`) is the primary usage. The `--subagent` mode is retained for backward compatibility and potential future use.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{YOK-N}` -- Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.
- `--subagent --session <id>` -- Run in subagent mode (no user interaction, auto-advance, exit 1 on failure).

## Constants

```text
MAX_ATTEMPTS=3
MAX_SIMULATOR_FIX_CYCLES=2
```

## Structured Field Write Rules

Never use ad-hoc body surgery. The item body is a generated view assembled by `python3 -m yoke_core.domain.render_body` from structured DB fields. Shepherd writes to isolated fields such as `shepherd_log` and `shepherd_caveats`, then re-renders the body through the items-update surface. Prefer stdin; use a body file only when you already have a real artifact file.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Each subagent you dispatch starts with zero context. The dispatch prompt is their entire world. Missing context in a dispatch prompt is the #1 cause of low-quality agent output.

**No such thing as "agent error."** When a subagent returns NOT_READY or low-quality output, the cause is systemic: insufficient dispatch context, truncated input, missing instructions, a file too large to read fully (P-50), or "you MUST" rules that failed under context pressure (P-26). Fix the dispatch, not the agent. Log the root cause in Ouroboros reflections.

**Events table for diagnosis.** When investigating why a subagent produced unexpected output, query the events table: `yoke events tail --limit 20`.

## Body Content Isolation Rules

The shepherd must not let item body content pollute its orchestration context.

1. Silent reads only. Read bodies into variables for structural checks; do not echo body content to stdout.
2. Discard after use. Once a body check is done, do not keep reusing the body content in context.
3. Subagents read body content independently from the DB.
4. If body text must appear inline, wrap it in explicit data fences.
5. Re-anchor between transitions so the shepherd stays in orchestrator mode.
6. For session-continuity context that successor agents need to resume after compaction, write to the **Progress Log** section on the epic item — see `AGENTS.md > Progress Log — long-running execution context on items`. Use this for shepherd-level state (which gates have run, which subagents are dispatched, which open questions remain) rather than `shepherd_log` (which is the structured verdict surface, not an execution scratchpad).

## Steps

### 1. Parse Arguments

Extract the numeric ID from `YOK-N` and detect standalone vs subagent mode.

### 2. Read Item

Load:

```bash
_num={N}
_type=$(yoke items get $_num type)
_item_status=$(yoke items get $_num status)
_title=$(yoke items get $_num title)
```

If any query returns empty, stop with `Item YOK-{N} not found.`

**Type gate:** If `_type` is not `epic`, reject immediately:
> Error: /yoke shepherd only supports epic items. YOK-{N} is type '{_type}'.
>
> Issue refinement routes through /yoke refine.
> Issue implementation routes through /yoke advance.
> Issue polish routes through /yoke polish.
>
> Run '/yoke refine YOK-{N}' to refine this issue.

**Status gate:** If `_item_status` is `idea` or `refining-idea`, reject:
> Error: YOK-{N} is at '{_item_status}' — shepherd requires epics at 'refined-idea' or later.
>
> Run '/yoke refine YOK-{N}' first to advance to refined-idea.

If the item is already `plan-drafted` or later in the epic progression, stop as a no-op.

After validation passes, register the work claim:

```bash
# Session touch + claim
yoke sessions touch --mode shepherd >/dev/null 2>&1 || true
yoke claims work acquire \
 --item "YOK-$_num"
```

### 3. Derive Transitions

Epic lifecycle (shepherd scope):
- `refined-idea` -> `refined_idea_to_planning`, `planning_to_plan_drafted`
- `planning` -> `planning_to_plan_drafted`
- _(`refining-plan` is owned by `/yoke refine`, not shepherd)_

### 4. Resume Logic

Before executing transitions, read prior verdict history:

```bash
_completed=$(yoke db read --format lines "SELECT transition FROM shepherd_verdicts WHERE item='YOK-$_num' AND (verdict='READY' OR verdict='CAVEATS' OR verdict='SKIPPED') ORDER BY id")
_blocked=$(yoke db read --format lines "SELECT transition FROM shepherd_verdicts WHERE item='YOK-$_num' AND verdict='BLOCKED' ORDER BY id")
```

Rules:
- READY / CAVEATS / SKIPPED -> skip the transition
- BLOCKED -> report and stop
- NOT_READY with attempts remaining -> resume at next attempt
- Otherwise -> execute from attempt 1

If all transitions are already complete, advance the item to `plan-drafted` and finish.

### 5. Execute Each Transition

For each remaining transition:

1. Set `_scholar_context=""` (Scholar is still a stub).
2. Gather prior caveats from earlier `CAVEATS` verdicts.
3. Route to the correct transition file:
 - `refined_idea_to_planning` -> [design-and-plan.md](design-and-plan.md)
 - `planning_to_plan_drafted` -> [planning-to-planned-gates.md](planning-to-planned-gates.md), then [boss-verdict.md](boss-verdict.md)
4. After any worker completes, always run [boss-verdict.md](boss-verdict.md) for the review, parsing, persistence, reflection, and retry/result logic.

### 6. Finalize And Report

After each verdict and after the full pipeline completes, read and follow [finalize.md](finalize.md).

That phase owns:
- Shepherd Log rendering and guarded writes
- Transition re-anchoring and auto-continuation
- Progress commits
- Final reporting
- Error handling and DB operations reference
