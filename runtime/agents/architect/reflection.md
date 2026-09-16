## End-of-session reflection

Read this at the end of your session. It is the full reflection contract and
what belongs in a field-note versus an Ouroboros entry.

## Ouroboros — End-of-Session Reflection

You are part of Ouroboros — Yoke's self-improvement system. Your observations feed the learning loop that makes Yoke better over time. Every friction point you notice, every idea you have, every "this should be easier" moment is valuable signal.

Before completing your final response, review your session and answer these **four** questions. For each question, aim for a comprehensive list — multiple answers are expected, not just one. Each question maps to exactly one `category` value in the entry block (named in bold).

1. **What problems did you encounter that code changes could prevent or improve?** — category **`problem`**. Errors, confusing interfaces, missing validations, unclear documentation, brittle patterns, anything that slowed you down or tripped you up.

2. **What are your best ideas for improving Yoke's processes?** — category **`process-improvement`**. The workflow, the agent handoffs, the task specs, the testing approach, the commit discipline, anything process-shaped that felt inefficient or error-prone.

3. **What game-changing features or capabilities would you build if you had a magic wand?** — category **`game-changing-idea`**. Automation, intelligence, integrations, developer experience improvements, or entirely new capabilities that would make Yoke dramatically better.

4. **What observations do you have about other agents' work?** — category **`cross-agent-critique`**. Quality of inputs received from upstream agents (specs from Product Manager, designs from Product Designer) and outputs expected by downstream agents (task specs for Engineer, validation criteria for Tester). Be specific about which agent and what improvement.

Use the canonical entry block exactly as defined in `runtime/agents/_shared/ouroboros-reflection-contract.md`. Set `agent: architect` and `context:` to the epic / PREFIX-N identifier you were planning. Use one of the four enum category values verbatim. The contract file includes a Pre-Submit Checklist — run through it once against your block before finalizing the response. The PostToolUse Agent-tool hook (`yoke_core.domain.reflection_capture_hook`) captures the block on subagent return and persists each entry. You do not write to the DB directly.

Architect worked example:

```
---REFLECTION-START---
---BEGIN ENTRY---
timestamp: 2026-05-15T19:30:00Z
agent: architect
context: epic PREFIX-N plan
category: process-improvement
Anticipation pass should resolve every AC-named CLI command to its argparse-owning leaf module via the dispatch table, then widen the path-claim to cover that file, so engineers do not pay the widen tax mid-implementation.
---END ENTRY---
---REFLECTION-END---
```
