# Wrapup — Record and Close

## 5. Observations

Write one Ouroboros entry per distinct observation, 1–3 concrete actionable
sentences. Use current UTC ISO-8601 time and stdin for the body:

```sh
yoke ouroboros entry insert --stdin --timestamp "{current UTC ISO 8601}" --agent conduct --context wrapup --category "{category}"
```

Categories: `problem` (failure), `friction` (harder than needed), `idea`
(improvement), `cross-critique` (tool/role feedback), `metric` (measurement),
`pattern` (confirmed recurrence). Keep unrelated observations separate.

## 6. Actionable follow-up

For each worthwhile problem/friction ask “File a work item for this?” with
its summary. On approval use `/yoke idea`; skip when none warrants an item.
Leave clustering, promotion and archiving to `/yoke curate`.

## 7–8. Authoritative continuity

Hold each relevant work claim while writing its checkpoint. Correct genuinely
changed spec/design/technical/test/deploy content through
`items.structured_field.replace`, with nonempty/nonshrinking preconditions.
Use the [typed envelopes](../idea/body-and-sync-functions.md).
Graph fields `worktree_plan`, `shepherd_log`, `shepherd_caveats` are epic-only
and must never be written for `generated_children=none`.

Execution continuity belongs in the timestamped Progress Log, rather than a
plan field or separate report store. Append a current-state checkpoint:

```sh
yoke items progress-log append PREFIX-N \
  --headline "Session checkpoint" \
  --content "Objective: ...
Standing decisions/holds: ...
Active work: ...
Blockers: ...
Next action: ...
Evidence: ..." \
  --source wrapup
```

For observations outside an item, append a field-note with the appropriate
kind and concrete evidence:

```sh
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence "..."
```

Record paths, next actions and evidence links; history stays in existing item
records and revisions. This checkpoint replaces a separate report artifact.

## 9. Summary

Display concise accomplishments/status changes, logged entry counts by
category, filed item refs/titles (or none), and unfinished business (or none).
State that continuity is in item Progress Logs and field-notes.

## 10. Artifacts

Commit any authored wrapup artifacts; the report is session output and needs
no generated file. Stage only intended paths, then commit when staged changes
exist. Preserve active work and release waits under their owning skill.
