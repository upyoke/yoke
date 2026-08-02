---
name: curate
description: Curate the Ouroboros learning log — cluster observations, promote field-notes to Dash, file work items for root causes.
argument-hint: "(no arguments)"
---

# /yoke curate

Curate the Ouroboros learning log. Process unreviewed agent observations — cluster related entries, route each cluster to the output that fits its size, and archive what has been handled.

This is entirely prompt-driven — no subagent is needed. You (the parent session) read the log, apply judgment, and use registered commands for the outputs.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Two outputs, sized to the cluster.** Most field-note clusters describe one concrete, instruction-sized repair: a recipe that names the wrong flag, a stale doc reference, an unhelpful denial message. Those go straight to a Dash — the promotion links the note to the Dash it produced, so the note is never re-clustered and the Dash carries its origin:

```bash
yoke ouroboros field-note promote {entry-id} --title "{specific title}" [--instruction "{what to do}"]
```

Reach for `/yoke idea` only when the cluster names a root cause that needs crafted acceptance criteria, design work, or more than one delivery slice.

**Field-notes are the primary channel.** Agents call `ouroboros.field_note.append` (CLI adapter: `yoke ouroboros field-note append --kind {failed|new|unclear|observation} --evidence TEXT`) when a recipe failed, was missing, or was unclear, and when they notice a minor bug best held as a supporting record. Read them through the dedicated reader — it is indexed on the entry table and needs no time window:

```bash
yoke ouroboros field-note list --unreviewed --project yoke
```

Treat a cluster of recipe gaps as a candidate recipe edit — repair the recipe in the matching packet seed file rather than promoting one Dash per signal.

**Events enrichment is a narrow lookup, not a sweep.** The events table is large enough that an unbounded query exceeds the statement timeout and comes back as a gateway error. When a cluster needs corroborating telemetry, ask for one event name over a short window with an explicit project and limit:

```bash
yoke events query --event-name {EventName} --project yoke --since "2 days ago" --limit 20
```

Widen the window only after the narrow query returns something worth chasing. Do not use `yoke events anomalies` over a multi-day window as a browsing step — it returns full envelopes and floods the session.

**Corrections supersede.** A note filed with `--corrects {entry-id}` links to the note it replaces and takes that note out of the unreviewed queue, so you cluster the correction rather than both. When two notes describe the same signal and one plainly restates the other without a link, they predate the link — cluster them together and mark both reviewed.

**File work items for root causes.** Every work item filed from curate should include perfect cold-start context: verified code references, concrete examples of what happened, and events telemetry. Frame every issue as what could have PREVENTED the agent from encountering it — missing guardrails, truncated context, file size limits, missing code-level enforcement. Never frame as "agent error."

## Steps

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active curate). Use the registered session wrapper:

```bash
yoke sessions touch \
 --mode curate
```

**Read and follow [cluster-and-work-item.md](cluster-and-work-item.md).** That file covers loading unreviewed entries, clustering, validating clusters against code and existing backlog items, routing each cluster to a Dash or a work item, and marking reviewed/archived entries.

Close the run with a retrospective in chat:

```text
# Ouroboros Retrospective

## Entries Processed
- Total entries examined: {N}
- By category: {category: count, ...}
- By author: {agent: count, ...}

## Clusters
- Clusters formed: {N}
- Dashes promoted: {N} ({PREFIX-N, ...})
- Work items filed: {N} ({PREFIX-N, ...})
- Entries skipped: {N}
- Entries deferred: {N}
- Clusters flagged as likely resolved: {N}

## Archiving
- Entries archived: {N}
- Entries remaining (unreviewed): {N}
```

## Notes

- This command is operator-invoked only. There is no auto-trigger.
- Entries are read through the registered Ouroboros readers, for example `yoke ouroboros entry list --unreviewed`.
- Mark reviewed entries through the registered lifecycle writer:
  `yoke ouroboros entry mark-reviewed {id}`.
- The `reviewed_at` timestamp mechanism ensures entries are only processed once (unless deferred). Promoting a note marks it reviewed as part of the promotion.
- Reviewed entries are archived immediately via
  `yoke ouroboros entry mark-archived --all-reviewed` — they remain in
  the DB but no longer appear in unreviewed queries.
- Recurring cross-run patterns live in `ouroboros/patterns.md` as institutional memory. Add to it when a cluster genuinely names a new recurring shape — not as a per-run step.
- Interactive filing goes through `/yoke idea`; this Yoke-owned workflow uses the issue workflow's authorized `harness_skill` entry surface so claims and GitHub sync stay on the product flow.
- This is part of Ouroboros — Yoke's self-improvement system. The learning loop: agents observe -> log to DB -> curate -> Dash or work item -> fix -> agents observe better.
