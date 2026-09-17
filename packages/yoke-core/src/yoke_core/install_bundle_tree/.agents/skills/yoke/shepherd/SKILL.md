---
name: shepherd
description: "Execute a pinned Shepherd planning segment through its quality gates"
argument-hint: "{PREFIX-N}"
---

# /yoke shepherd {PREFIX-N}

Execute the `shepherd` segment registered by the item's immutable workflow
version, applying Boss quality gates at every transition. Each step is: Worker
produces artifact -> Boss reviews -> persist verdict -> advance or retry.

Shepherd is selected by an active `skill_bindings` interval, not by an item
type or workflow id. This implementation supports the generated-task planning
contract (`generated_children=epic_tasks`) and verifies the exact pinned
segment before it writes anything.

> Standalone mode (`/yoke shepherd PREFIX-N`) is the primary usage. The `--subagent` mode is retained for backward compatibility and potential future use.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{PREFIX-N}` -- Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.
- `--subagent --session <id>` -- Run in subagent mode (no user interaction, auto-advance, exit 1 on failure).

## Constants

```text
MAX_ATTEMPTS=3
MAX_SIMULATOR_FIX_CYCLES=2
```

## Structured Field Write Rules

Never use ad-hoc body surgery. The item body is a generated view assembled by `python3 -m yoke_core.domain.render_body` from structured DB fields. Shepherd writes to isolated fields such as `shepherd_log` and `shepherd_caveats`, then re-renders the body through the items-update surface. Prefer stdin; use a body file only when you already have a real artifact file.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent. Each subagent you dispatch starts with zero context. The dispatch prompt is their entire world for this phase — self-contained for the current dispatch, not an accumulated essay. Missing context in a dispatch prompt is the #1 cause of low-quality agent output.

**No such thing as "agent error."** When a subagent returns NOT_READY or low-quality output, the cause is systemic: insufficient dispatch context, truncated input, missing instructions, a file too large to read fully (P-50), or "you MUST" rules that failed under context pressure (P-26). Fix the dispatch, not the agent. Log the root cause in Ouroboros reflections.

**Events table for diagnosis.** When investigating why a subagent produced unexpected output, query the events table: `yoke events tail --limit 20`.

## Body Content Isolation Rules

The shepherd must not let item body content pollute its orchestration context.

1. Silent reads only. Read bodies into variables for structural checks; do not echo body content to stdout.
2. Discard after use. Once a body check is done, do not keep reusing the body content in context.
3. Subagents read body content independently from the DB.
4. If body text must appear inline, wrap it in explicit data fences.
5. Re-anchor between transitions so the shepherd stays in orchestrator mode.
6. For session-continuity context that successor agents need to resume after compaction, write to the **Progress Log** section on the task-graph parent item — see `AGENTS.md > Progress Log — long-running execution context on items`. Use this for shepherd-level state (which gates have run, which subagents are dispatched, which open questions remain) rather than `shepherd_log` (which is the structured verdict surface, not an execution scratchpad).

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–2. Parse and read | `/yoke shepherd PREFIX-N` was just invoked | [`entry.md`](entry.md) |
| 3–6. Derive, resume, execute, finalize | The item and its pin are read and claimed | [`transitions.md`](transitions.md) |

Each transition names the gate document it needs; read those only when the
transition you are executing selects them.

## Start

Read [`entry.md`](entry.md) and follow it.
