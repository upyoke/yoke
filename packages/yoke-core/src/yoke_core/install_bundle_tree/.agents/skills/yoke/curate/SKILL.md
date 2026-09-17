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

**Two outputs, by execution shape.** Most field-note clusters describe one
concrete repair a session can state as an instruction and execute directly.
Those go straight to a Dash, whose promotion links the note to its output. Resolve the note or cluster's project,
call registered `workflow.execution_instruction.resolve`, and apply every
returned instruction before finalizing the promotion title or instruction:

```bash
yoke workflow execution-instruction resolve --workflow dash --project {project}
yoke ouroboros field-note promote {entry-id} --title "{specific title}" [--instruction "{what to do}"]
```

Reach for `/yoke idea` only when the cluster needs a structure a Dash does not give it — crafted acceptance criteria to agree on, or a generated task graph across parallel lanes. Volume alone does not: a large repair stated as one instruction is still a Dash.

**Field-notes are the primary channel.** Agents call `ouroboros.field_note.append` (CLI adapter: `yoke ouroboros field-note append --kind {failed|new|unclear|observation} --evidence TEXT`) when a recipe failed, was missing, or was unclear, and when they notice a minor bug best held as a supporting record. Read them through the dedicated reader — it is indexed on the entry table, needs no time window, and is always bounded (default newest 50). Count first, then page:

```bash
yoke ouroboros field-note list --unreviewed --count
yoke ouroboros field-note list --unreviewed --limit 50
yoke ouroboros field-note list --unreviewed --limit 50 --offset 50
```

Treat a cluster of recipe gaps as a candidate recipe edit — repair the recipe in the matching packet seed file rather than promoting one Dash per signal.

**Events enrichment is a narrow lookup, not a sweep.** The events table is large enough that an unbounded query exceeds the statement timeout and comes back as a gateway error. When a cluster needs corroborating telemetry, ask for one event name over a short window with an explicit project and limit:

```bash
yoke events query --event-name {EventName} --project yoke --since "2 days ago" --limit 20
```

Widen the window only after the narrow query returns something worth chasing. Do not use `yoke events anomalies` over a multi-day window as a browsing step — it returns full envelopes and floods the session.

**Corrections supersede.** A note filed with `--corrects {entry-id}` links to the note it replaces and takes that note out of the unreviewed queue, so you cluster the correction rather than both. When two notes describe the same signal and one plainly restates the other without a link, they predate the link — cluster them together and mark both reviewed.

**File work items for root causes.** Every work item filed from curate should include perfect cold-start context: verified code references, concrete examples of what happened, and events telemetry. Frame every issue as what could have PREVENTED the agent from encountering it — missing guardrails, truncated context, file size limits, missing code-level enforcement. Never frame as "agent error."

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| Curate | `/yoke curate` was just invoked | [`run.md`](run.md) |
| — Cluster into a work item | The run reaches the clustering step | [`cluster-and-work-item.md`](cluster-and-work-item.md) |

## Start

Read [`run.md`](run.md) and follow it.
