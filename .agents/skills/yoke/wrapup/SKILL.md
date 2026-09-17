---
name: wrapup
description: "Structured session wrap-up: ouroboros reflections, unfinished business, session summary."
argument-hint: "(no arguments)"
---

# /yoke wrapup

Structured end-of-session wrap-up. Reviews the session's work, logs ouroboros reflections, captures unfinished business, and offers to file work items for discovered issues.

This is the bookend to session-start — if we enforce how sessions begin, we enforce how they end.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Events table summary.** During the session review, query the events table for this session's telemetry: `yoke events count --since "4 hours ago"` for volume and `yoke events anomalies --since "4 hours ago"` for failure patterns. Include a brief events summary in the wrapup report.

**Be the giant.** Leave a current-state checkpoint, not an accumulated essay. The wrapup and Progress Log carry the live objective, standing decisions/holds, active work, blockers, next actions, and links to durable evidence. History stays in item records and document revisions; do not restate full results or stale snapshots. After compaction, reload this skill — discarded context is gone.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–4. Survey and report | `/yoke wrapup` was just invoked | [`survey-and-report.md`](survey-and-report.md) |
| 5–10. Record and close | The report is generated | [`record-and-close.md`](record-and-close.md) |

## Start

Read [`survey-and-report.md`](survey-and-report.md) and follow it.
