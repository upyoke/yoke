---
name: curate
description: Curate the Ouroboros learning log — cluster observations, promote field-notes to Dash, file work items for root causes.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "(no arguments)"
---


# /yoke curate

Operator-invoked, prompt-driven curation; the parent session applies judgment
without a subagent or automatic trigger. Cluster unreviewed observations,
validate the current root cause, approve an output and archive handled entries.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Choose output by execution shape: one concrete instruction goes to Dash even
when large; agreed acceptance criteria or a parallel task graph goes through
`/yoke idea`. Resolve the project and full workflow execution instructions
before finalizing the output. Recipe-gap clusters may need one edit to the
matching packet seed rather than one Dash per note.

Use verified code references, examples and telemetry to explain what the
system should change to prevent recurrence. Frame failures as what the system should change, never as "agent error";
identify missing guardrails, context or enforcement.

## Phase map — read before acting

| Phase | Read |
|---|---|
| Begin and summarize | [run.md](run.md) |
| Load, cluster, validate, approve, file and archive | [cluster-and-work-item.md](cluster-and-work-item.md) |

Start with run.md.
