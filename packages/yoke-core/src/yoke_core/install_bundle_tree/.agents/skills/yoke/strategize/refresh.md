# Strategize — refresh and checkpoints 0–1

## Bound the delta with project state

```sh
yoke strategy checkpoint latest --project <project>
yoke strategy doc list --project <project>
```

Window starts at this project's latest `strategy_checkpoints` timestamp.
If absent, newest reviewed SML row's updated_at; if none, last 14 days.
Print start/end/source (`checkpoint`, `sml_doc_write`, `default_14d`).
Events are audit telemetry, never the delta authority.

Read all five docs once, keeping structure/dates and updated_at CAS bases:

```sh
yoke strategy doc get MISSION
yoke strategy doc get LANDSCAPE
yoke strategy doc get VISION
yoke strategy doc get MASTER-PLAN
yoke strategy doc get CURRENT-PLAN
git log --oneline --since="<window-start>" -- . | head -30
yoke items list --project <project> --fields "id,title,status,workflow_id,workflow_version_id"
yoke events query --event-name SMLChangeApproved --project <project> --limit 10
```

Commit/board recent-done samples are presentation-only: cap board display at 30
and recent done at 10, with 5–8 notable commit themes. Count active statuses
excluding idea/done/cancelled/failed/stopped; list in-flight epic tasks using
`yoke epic-tasks list --epic <epic-ref>`. Doc list updated_at/updated_by names
recent changed docs; rendered strategy history is not git history.
Diagnostic SQL reads `NULLIF(envelope, '')::jsonb -> 'context' AS context`
for `event_name = 'SMLChangeApproved'`, scoped to this project.

## Complete bounded landed-work carry

Registered owner discovers merged landings once, preserves existing state and
pending carry beyond its discovery horizon. Defaults are source constants:
60 days and 200 pending candidates; registered horizon/cap flags override.
Keep the same chosen window/cap for all three calls. Capture `new_ids` once:

```sh
yoke strategy carry register-new --project <project> --result-json
yoke strategy carry summary --project <project> --new-ids ${_carry_new_ids}
yoke strategy carry candidate-set --project <project> --new-ids ${_carry_new_ids}
```

Take `_carry_new_ids` from register-new JSON, without rediscovery.
Summary is read-only/display-limited; retain it and candidate-set JSON.
The latter owns the full capped new/carry_forward/reflected/dismissed buckets.
Show truncation explicitly and include ALL returned pending records, rather
than letting a display sample decide eligibility.

Derive `_carry_total_pending=` candidate-set total_pending and
`_carry_new_count=` length of new. Keep JSON for change matching/resolution;
new_ids must classify both rendered summary and structured set consistently.

## Checkpoint 0 — state confirmation

Present `## State Refresh Summary`: delta/source; one-line state of all five
docs; notable activity/changed docs; active/recent-done samples/in-flight epics
with task counts; carry summary verbatim plus full bounded pending records;
observations of drift, stale sections or unresolved carry imbalance.
Summarize to the operator rather than echoing complete docs.

Ask in plain chat whether it matches reality: continue/confirmation synonyms,
freeform corrections, or abort. Confirmation records `cp0:confirmed`.
Corrections fold into summary and re-present until accepted.
Abort records `cp0:aborted`, follows entry's release contract and stops.
Unclear intent: one chat clarifier.

## Checkpoint 1 — problem framing

Ask what strategic question to resolve, accepting freeform specific concern
or general coherence review. Record verbatim `_problem_framing` and
`_framing_type=specific|general_coherence`; checkpoint outcome matches it.
Ambiguity: one clarifier before fixing framing. Abort releases/stops.

After both checkpoints, emit SMLRefreshCompleted (lifecycle/strategize/skill,
INFO/completed/project) with JSON context:
delta_source, sml_files_changed, active_items, problem_framing (framing type),
carry_horizon_days, carry_limit, carry_total_pending, carry_new_this_session.
Counts/window come from the observed set, not guessed defaults.
Pass confirmed summary/framing/window to Research.
