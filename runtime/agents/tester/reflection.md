# Tester — Ouroboros End-of-Session Reflection

Before final verdict sweep all useful observations, multiple where warranted:
- `problem`: infrastructure/fixtures/diffs/receipt issues that obstructed review.
- `process-improvement`: Engineer handoff, dispatch, receipts, regression cadence.
- `game-changing-idea`: transformative review/triage/AC verification capabilities.
- `cross-agent-critique`: concrete Engineer/Architect input/output improvement.

Read `runtime/agents/_shared/ouroboros-reflection-contract.md`, run Pre-Submit
Checklist and emit canonical envelope with agent: tester, real public-ref/task
context, exact categories and one entry per observation. Parent PostToolUse
Agent-tool hook (`yoke_core.domain.reflection_capture_hook`) persists entries;
Tester never writes reflection rows directly. Empty envelope records clean no-op.

Reflection precedes final message's exactly one `**VERDICT: PASS**` or
`**VERDICT: FAIL**` line, required by Structured Verdict Requirement.
