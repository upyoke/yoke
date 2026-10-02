# Events, Doctor, Ouroboros

## Events

Workbench **Events** is the audit stream: lifecycle, claims, deploy, doctor
findings, function calls. Filter by name and time when debugging "what
happened."

**Search loaded events** searches the entries already loaded and offers
observed names as suggestions. Advanced filters keep the precise server-side
event name, source, severity and time constraints. The loaded scope remains
explicit; text search does not promise matches outside it.

## Doctor

Workbench **Doctor** runs health checks: backlog consistency, GitHub sync,
worktrees, docs drift, dispatch chains, project-local checks under
`.yoke/doctor/`.

```bash
yoke doctor run --quick
yoke doctor run --full --fix   # when auto-repair is appropriate
```

Checks declare applicability (project scope, capabilities, runtime). Results
are pass, warning, fail, or not-applicable — N/A is not a silent pass.
On Linux, Doctor warns about project checkouts under `/mnt/<drive>`; inside
WSL it also warns when systemd is not PID 1. See
[Yoke on Windows (WSL)](windows-wsl.md) for the recovery steps. These machine
checks report N/A on other operating systems.

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
Each row links a bounded evidence preview to the complete note. The roster
reads only the preview, keeps newest-first paging, and labels review/category
filters; opening a note retrieves the full evidence.

```bash
yoke ouroboros field-note append --kind observation --evidence '...'
 /yoke curate
```

Session continuity for long work also belongs on the item **Progress Log**.
