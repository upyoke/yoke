---
name: curate
description: Curate the Ouroboros learning log — cluster observations, file tickets, archive old entries, promote recurring patterns.
argument-hint: "(no arguments)"
---

# /yoke curate

Curate the Ouroboros learning log. Process unreviewed agent observations — cluster related entries, propose tickets, archive old entries, and promote recurring patterns.

This is entirely prompt-driven — no subagent is needed. You (the parent session) read the log, apply judgment, and use existing scripts for ticket creation.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Events table enrichment.** When clustering observations, query the events table for corroborating telemetry. An observation saying "tests failed unexpectedly" becomes actionable when paired with events data showing repeated `nonzero_exit` anomalies from a specific script. Use `yoke events anomalies --since "7 days ago"` to enrich clusters.

**Field-note enrichment.** Agents call `ouroboros.field_note.append` (CLI adapter: `yoke ouroboros field-note append --kind {failed|new|unclear|observation} --evidence TEXT`) when a Tier-1 packet recipe failed, was missing, had unclear purpose, or when they notice a minor bug not worth a ticket. Each call emits an `OuroborosFieldNoteAppended` event. Surface them alongside the freeform log via `yoke events query --event-name OuroborosFieldNoteAppended --since "7 days ago"` and treat clusters as candidate recipe edits — paste/repair the recipe in the matching packet seed file rather than filing a separate ticket per signal.

**File tickets for root causes.** Every ticket filed from curate should include perfect cold-start context: verified code references, concrete examples of what happened, and events telemetry. Frame every issue as what could have PREVENTED the agent from encountering it — missing guardrails, truncated context, file size limits, missing code-level enforcement. Never frame as "agent error."

## Steps

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active curate). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode curate
```

1. **Read and follow [cluster-and-ticket.md](cluster-and-ticket.md).**
 This phase covers loading unreviewed entries, clustering, validating clusters against code and existing backlog items, creating approved tickets, and marking reviewed/archived entries.

2. **Read and follow [patterns-and-retro.md](patterns-and-retro.md).**
 This phase covers recurring-pattern promotion and the final Ouroboros retrospective summary.

## Notes

- This command is operator-invoked only. There is no auto-trigger.
- Entries are read through the registered Ouroboros readers, for example `yoke ouroboros entry list --unreviewed`.
- Mark reviewed entries through the registered lifecycle writer:
  `yoke ouroboros entry mark-reviewed {id}`.
- The `reviewed_at` timestamp mechanism ensures entries are only processed once (unless deferred).
- Reviewed entries are archived immediately via
  `yoke ouroboros entry mark-archived --all-reviewed` — they remain in
  the DB but no longer appear in unreviewed queries.
- Pattern detection uses semantic similarity (LLM judgment), not exact string matching.
- All ticket creation goes through `/yoke idea` so intake provenance, claims, and GitHub sync stay on the product flow.
- This is part of Ouroboros — Yoke's self-improvement system. The learning loop: agents observe -> log to DB -> curate -> ticket -> fix -> agents observe better.
