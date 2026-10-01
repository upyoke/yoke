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
yoke doctor run --quick
yoke doctor run --full --fix   # when auto-repair is appropriate
```

Checks declare applicability (project scope, capabilities, runtime). Results
are pass, fail, or not-applicable — N/A is not a silent pass.

The CLI runs machine-local checks on the client even when the control plane
is hosted. A machine-only `--only` selection stays local; a mixed selection
relays the control-plane checks and combines their results. New client checks
do not depend on the server having the same roster. The `hook-resident` check
reports an unavailable resident as WARN while hooks continue through their
canonical in-process fallback:

```bash
yoke watch doctor -- --only hook-resident
```

## Ouroboros

Self-improvement loop: field-notes and observations → curate → doctor →
simulate. Workbench **Ouroboros** surfaces entries and field-notes.

```bash
yoke ouroboros field-note append --kind observation --evidence '...'
 /yoke curate
```

Session continuity for long work also belongs on the item **Progress Log**.
