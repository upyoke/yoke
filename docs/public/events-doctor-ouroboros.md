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

Each check has a 45-second budget. PostgreSQL statements use the remaining
budget as a statement timeout. A thread-local Python trace enforces the
wall-clock deadline even for checks with no SQL or explicit clock probes;
the caller's trace is restored afterwards. Database operations defer Python
deadline exceptions until the driver returns, so protocol frames are never
interrupted. PostgreSQL connections lacking `autocommit` refuse with
`doctor_postgres_autocommit_unavailable` and teach the required connection.
The shared HTTP and subprocess helpers consume the same deadline. A timeout reports
`HC-check-incomplete` with `doctor_check_budget_exhausted` and a recovery step;
partial pass/fail verdicts are discarded. Transaction recovery completes before
the next check runs, and recovery failures remain visible in the incomplete result.
Project checks must use bounded I/O helpers for blocking operations.
The obsoleted-term scan overlaps independent file reads while preserving
path and finding order. A conservative required-literal test avoids per-line regex
work only when a mandatory leading sequence or every complete literal choice is absent;
patterns without a provable candidate retain the entire line scan. The original per-pattern tests, path exemptions, slash
normalization, line matching and full-tree coverage remain the same.
Provenance, hook-boundary and file-line checks overlap their complete inventories'
independent reads. Hook and platform namespace boundaries also evaluate each
file's complete AST predicates in that bounded pool; ordered results retain
every finding without serializing the full AST walk on the traced caller.
The item-reference check reads each source once for its six
scans; historical-reference scanning avoids AST work only when no reference
matches anywhere in the file. The add-column and ambient-connection guards
likewise prefetch every scoped source without changing their AST predicates.
CLI help coverage overlaps all isolated entrypoint processes, each using the
remaining deadline; child timeouts deterministically report `HC-check-incomplete`.
Atlas captures its complete help roster in one isolated,
deadline-bound child; stdout redirection stays serial within that child.
Exemptions and finding order remain unchanged.
Worktree-health likewise overlaps every lane's independent status read under
that deadline and resolves disposable roots per lane when no repository root
is available. Delegated sync avoids fetching comparison fields when linkage
has already found no paired subjects; its orphan classifications still run.

A full HTTPS report includes the caller's complete project-local check roster.
Mixed source/backlog checks retain their own named N/A when direct database
authority is unavailable; that surface limit is never an internal-error verdict.
Completed source findings survive alongside the DB-half N/A, including multiple
verdicts from the same check; composition never overwrites those findings.
Source checks retain the runner's scoped checkout binding without local SQL.
When the imported engine runs from a linked lane of the mapped project repo,
that lane supplies candidate source; another project's checkout keeps its own
binding. Missing control-plane reads remain visible as N/A rather than a pass.
Git identity read failures surface `doctor_source_checkout_fallback`, the mapped
checkout used, and recovery instructions instead of silently switching trees.
Composition preserves every named incomplete or internal error; distinct check
failures never replace one another merely because they share a reserved HC id.

The claim-boundary audit inspects the full audit history, retaining its explicit
configured event-id cutoff. Historical event-outcome drift also inspects every
candidate. Both compute totals and correlation in SQL and return only bounded
finding previews; neither a time window nor a candidate-row cap hides history.
A statement timeout or exhausted clock budget reports incomplete evidence.

HTTPS chunks carry one check and spend at most 60 seconds across at most
two attempts, including retry delays. The remote roster has a 15-minute
overall deadline. Failed chunks retain completed rows, the last cursor,
and the original error and request identity in a failing partial report.
Transport errors and handler failures both continue native runtime and
source checks; a failed hosted batch never suppresses local relay evidence.
Request validation refusals retain their original error without a partial report.
Retry a named check with `yoke watch doctor -- --only <slug>` after the
provider or control plane recovers. The `wrong-repo-issues` check filters
same-repository rows before rendering references and caches paginated
repository inventories, including closed issues, for the whole check.

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


The Ouroboros dashboard labels filing timestamps as **Filed at** and defaults to newest first. Observation, project, Filed at, Category, Context and Reviewed headers sort the matching roster before cursor pagination. Sort choices use the existing actor/universe preference store and restore across browsers and devices. The repetitive executor column is omitted; complete entry details remain available. Narrow layouts expose labeled row values and keep sort controls available.
