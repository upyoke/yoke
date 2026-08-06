# Events, Doctor, Ouroboros

## Events

Workbench **Events** is the audit stream: lifecycle, claims, deploy, doctor
findings, function calls. Filter by name and time when debugging "what
happened."

## Doctor

Workbench **Doctor** runs health checks: backlog consistency, GitHub sync,
worktrees, docs drift, dispatch chains, project-local checks under
`.yoke/doctor/`.

```bash
yoke doctor
yoke doctor --fix   # when auto-repair is appropriate
```

Checks declare applicability (project scope, capabilities, runtime). Results
are pass, fail, or not-applicable — N/A is not a silent pass.

## Ouroboros

Self-improvement loop: field-notes and observations → curate → doctor →
simulate. Workbench **Ouroboros** surfaces entries and field-notes.

```bash
yoke ouroboros field-note append --kind observation --evidence '...'
 /yoke curate
```

Session continuity for long work also belongs on the item **Progress Log**.
