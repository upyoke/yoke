# Ouroboros Reflection Contract (shared)

Canonical reflection shape for every Yoke role. Role prompts supply their
specific sweep; this file owns invariant categories, fields and delimiters.
The PostToolUse Agent-tool hook (`yoke_core.domain.reflection_capture_hook`)
captures entries when the subagent returns. Parser alternatives in
`yoke_core.domain.reflection_capture_shapes` are not authoring templates.

## Category Enum (use one of these values)

Use exactly one lowercase, hyphenated value per observation; no aliases:

- `problem`: friction, errors, brittle interfaces, missing validation/docs.
- `process-improvement`: workflow, handoffs, specs, testing or commit discipline.
- `game-changing-idea`: transformative automation, intelligence, integrations
  or developer capabilities.
- `cross-agent-critique`: specific improvements to another role's upstream
  input or expected downstream output; name the role and improvement.

## Canonical Entry Block

Final response contains one outer envelope and one entry per observation.
Every entry has four lowercase field-led rows, in any order, then plain prose.
Keys use `: `; body runs from the last field to the closing entry delimiter.
Use a real timestamp, dispatched role and nonempty real epic/task/public ref.
Roles: `engineer`, `tester`, `architect`, `simulator`, `boss`, `product-manager`,
`product-designer`, `qa-walker`.

```text
---REFLECTION-START---
---BEGIN ENTRY---
timestamp: 2026-05-15T18:00:00Z
agent: ROLE
context: PREFIX-N or epic/task identifier
category: problem
Specific observation: what happened, what was expected, what would improve it.
Multi-line bodies are preserved verbatim.
---END ENTRY---
---REFLECTION-END---
```

Replace placeholders. Repeat only the inner entry block for more observations.

## Pre-Submit Checklist

Before final response, check every entry; malformed canonical records can be
lost or reduced to lossy fallback records:

- Exactly one `---REFLECTION-START---` / `---REFLECTION-END---` pair per response.
- One `---BEGIN ENTRY---` / `---END ENTRY---` pair per observation.
- All four rows: `timestamp:`, `agent:`, `context:`, `category:`. Lowercase keys,
  colon-space, one row per field; body immediately follows last field, with no
  separator or code fence (blank line unnecessary).
- Exact category enum, lowercase with hyphens; friction maps to `problem`,
  ideas to process or transformative categories by scope.
- Agent matches dispatching role exactly; context is real, never empty or a
  placeholder. Body is concrete and belongs to that category.

With no observations emit `---REFLECTION-START---` immediately followed by
`---REFLECTION-END---`. Empty envelope records a truthful no-op; missing
reflection silently leaves the orchestrator without that record.
