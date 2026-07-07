# Ouroboros Reflection Contract (shared)

Single source of truth for the Ouroboros reflection entry shape. Every Yoke agent that emits reflections references this file from its own reflection section so the contract cannot drift across roles. Agents inline their role-specific intro and sweep questions; the contract bullets below are invariant across roles.

## Category Enum (use one of exactly these four values)

Each end-of-session sweep question maps to exactly one `category` value. Use the value verbatim — lowercase, hyphens (not underscores), no aliases, no uppercase, no other inventions.

- **`problem`** — friction, errors, brittle interfaces, missing validations, unclear docs, anything that slowed the session down or tripped the agent up.
- **`process-improvement`** — better workflow, agent handoffs, task specs, testing approach, commit discipline, anything process-shaped that felt inefficient.
- **`game-changing-idea`** — automation, intelligence, integrations, developer experience, ambitious capability ideas that would make Yoke dramatically better.
- **`cross-agent-critique`** — observations about other agents' work: quality of upstream inputs received, fit of expected downstream outputs. Be specific about which agent and what improvement.

## Canonical Entry Block

Include reflections in the final response using the exact delimited block below. The PostToolUse Agent-tool hook (`runtime/api/domain/reflection_capture_hook.py`) parses this block automatically when the subagent's `Agent` tool call returns; the multi-shape parser in `runtime/api/domain/reflection_capture_shapes.py` accepts shapes A..H plus a freeform fallback, but the canonical shape below is the one PMs / PDs / Engineers / Testers / Simulators / Architects / Boss / Conduct teach to keep the parser benchmark clean:

- **Outer envelope:** one `---REFLECTION-START---` line and one `---REFLECTION-END---` line per response.
- **Each entry:** a `---BEGIN ENTRY---` line, four field-led rows (`timestamp:`, `agent:`, `context:`, `category:`) in any order, the body, and a `---END ENTRY---` line.
- **Field rows** use lowercase keys followed by `: ` and the value. The body is every line after the last field row and before `---END ENTRY---`.
- **`agent:`** is the agent's role name (`engineer`, `tester`, `architect`, `simulator`, `boss`, `product-manager`, or `product-designer`).
- **`context:`** names the epic/task/YOK-N being worked on (e.g., `YOK-N task 001`, `conduct epic YOK-N`). Never empty.
- **`category:`** is one of the four enum values above. Lowercase. Hyphens, not underscores. No other values.

Skeleton (replace `ROLE`, timestamp, context, body with actual values):

```
---REFLECTION-START---
---BEGIN ENTRY---
timestamp: 2026-05-15T18:00:00Z
agent: ROLE
context: YOK-N or epic/task identifier
category: problem
The body is plain prose describing the observation: what happened, what
was expected, what would be better. Multi-line bodies are preserved
verbatim by the parser. Be specific.
---END ENTRY---
---REFLECTION-END---
```

Repeat the `---BEGIN ENTRY--- ... ---END ENTRY---` block once per observation.

## Pre-Submit Checklist

Before emitting your final response, verify every entry block against this checklist. The parser is strict on the canonical shape; an entry that fails any check below either drops on the floor or lands with a lossy fallback record.

- The full block is wrapped in exactly one `---REFLECTION-START---` line and one `---REFLECTION-END---` line.
- Every entry is wrapped in `---BEGIN ENTRY---` and `---END ENTRY---` (both required, one of each per entry).
- Every entry contains all four field rows: `timestamp:`, `agent:`, `context:`, `category:`. Field keys are lowercase, followed by `: ` and the value, one per line.
- `category:` value is one of exactly four strings: `problem`, `process-improvement`, `game-changing-idea`, `cross-agent-critique`. Lowercase. Hyphenated. Map every observation to one of these — a "friction" is a `problem`; an "idea" is either `process-improvement` or `game-changing-idea` depending on scope.
- `agent:` value matches the dispatching role exactly (e.g., `engineer`, `tester`, `architect`, `simulator`, `boss`, `product-manager`, `product-designer`).
- `context:` value names a real epic/task/YOK-N identifier — never empty, never a placeholder.
- The body begins on the line immediately after the last field row. No separator line, no code fence, no blank line required.

If the dispatch genuinely produced no observations, emit an empty envelope (`---REFLECTION-START---` immediately followed by `---REFLECTION-END---`) rather than skipping the block. An empty envelope is a truthful no-op; a missing block makes the orchestrator's reflection step go silent without recording why.
