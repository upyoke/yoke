# Doctor

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Operations](index.md) > Doctor
<!-- /yoke:breadcrumbs -->

Run applicable health checks and interpret complete, incomplete and unavailable evidence.

## Doctor

Workbench **Doctor** runs health checks: backlog consistency, GitHub sync,
worktrees, docs drift, dispatch chains, project-local checks under
`.yoke/doctor/`.

```bash
yoke doctor run --quick
yoke doctor run --full --fix   # when auto-repair is appropriate
```

Doctor watchers emit a filtered stream with progress metadata, not a bare JSON
document. QA probes retain explicit raw captures and read the single
`doctor.run.run` envelope from that capture before judging completeness.

Checks declare applicability (project scope, capabilities, runtime). Results
are pass, warning, fail, or not-applicable — N/A is not a silent pass.
On Linux, Doctor warns about project checkouts under `/mnt/<drive>`; inside
WSL it also warns when systemd is not PID 1. See
[Yoke on Windows (WSL)](../start/windows-wsl.md) for the recovery steps. These machine
checks report N/A on other operating systems.

From a folder outside every project, Doctor runs only its machine-scope
checks, which read this machine's harness homes, hooks, relay and
connections. It reports each project-scope check it skipped as N/A with
`project_required` and the recovery: rerun from a project folder or add
`--project P`. A selection with no machine-scope check refuses
`project_required`. Repair missing machine setup, such as the `yoke-global`
skill or machine-wide harness hooks, from any folder:

```bash
yoke doctor run --only harness-setup --fix
```

Harness homes identify configuration that setup can manage; they do not prove
that a CLI, desktop app or editor extension is installed. CLI checks use the
same PATH-first, then bundled-executable resolver as relay probes. Dashboard
onboarding and machine detail use the same surface-specific relay observations:
“not observed” means installation is unproved, including unsupported extension
detection. Hook trust and session activity describe configuration and readiness
separately; the session roster does not scan unrelated desktop applications.

Each check has a 45-second budget. Each PostgreSQL transaction arms the
remaining budget as its statement timeout once, when it starts. The wall clock
is checked at I/O boundaries and again when the check returns; running Python,
subprocesses and driver protocol frames are never interrupted, so a check that
overruns without blocking I/O reports incomplete once it returns. PostgreSQL
connections lacking `autocommit` refuse with
`doctor_postgres_autocommit_unavailable` and teach the required connection.
Parallel read submission rechecks the remaining budget before admitting each task;
expiry cancels queued reads without waiting for running I/O to finish.
Identifier rendering scans prefetch their full source inventory through the same
bounded reader pool and use mandatory syntax and identifier literals to avoid
regex backtracking; their matching rules, source inventory and exemptions are unchanged.
The shared HTTP and subprocess helpers consume the same deadline. A timeout reports
`HC-check-incomplete` with `doctor_check_budget_exhausted` and a recovery step;
partial pass/fail verdicts are discarded. Repairs a `--fix` run already
committed are kept, and its recovery step repeats `--fix` so a retry continues
from them. Transaction recovery completes before
the next check runs, and recovery failures remain visible in the incomplete result.
Project checks must use bounded I/O helpers for blocking operations.
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
When the imported engine runs from a linked lane, or a disposable clone whose
local Git origin is the mapped project checkout, that tree supplies candidate
source. Another project's checkout keeps its own binding. Missing control-plane
reads remain visible as N/A rather than a pass.
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
requires a live resident running the installed build. A missing, stale or
unknown build fails with a new-session recovery; its read-only health probe
does not evaluate hooks or restart the process:

```bash
yoke watch doctor -- --only hook-resident
```

For first-use readiness, select the install roster:

```bash
yoke doctor run --install --project P
```

This checks machine registration, relay, hook version, unattended permissions,
configured GitHub auth, native CLI sign-in, dashboard build, observed session
hook registration, foreign install residue, installed guidance and instruction
discovery. Outside a project it runs the machine checks and reports GitHub
auth, residue, guidance and discovery as N/A. Each failure gives one next step. Intentional GitHub disablement is
N/A; absent or unknown evidence is not a pass. Guidance checks prove installed
configuration, while the session check requires both registration and confirmed
hook delivery. Full-corpus audits remain in the full Doctor selection.

Outside an agent session, ordinary Doctor runs (including `--quick`) report
session hook registration, harness sign-in and unattended posture as N/A with
`session_required`. The health receipt shown by `yoke status` retains these
skips. Explicit `--session`, `--install` or `--only` selections still require
the selected session evidence and fail when it is missing.

Before onboarding, check only the session you are in:

```bash
yoke doctor run --session
```

This checks that the session is registered with confirmed hook delivery, and
that its own harness CLI is signed in and runs `yoke` without approval
prompts. Other installed harnesses do not block it. Agent setup ends with this
check and `/yoke onboard` runs it first.

Claude CLI sessions read `~/.claude/settings.json` for
`permissions.defaultMode`; Claude Desktop sessions read the app preference.
The registered session surface chooses the check, so CLI readiness does not
require a Desktop installation. An unknown or unsupported Claude surface
reports unverified posture instead of borrowing Desktop settings.
Either surface also passes when you keep your own mode and
`~/.claude/settings.json` `permissions.allow` holds the `Bash(yoke:*)` entry
setup adds; Codex and Cursor pass the same way with their own `yoke` entry.

The session check also works outside every project: registration and confirmed
orientation use the selected authority's machine scope. An explicit `--project`
still requires that same project registration. Missing delivery, a project
mismatch and an unreadable authority retain their own failure reasons.

## Writing a health check

- Each check declares its `project_scope` (`any`, `self`, `external`), whether
  it reads the source tree, its runtimes (`local`, `server`, `hosted`) and the
  capabilities it needs. The runner derives the applicable set; never branch
  on a project slug. No mapped project refuses `project_required`.
- A check outside the applicable set reports `N/A` with its reason (in
  `## Not Applicable` and `na_count`), never `PASS`.
- Project checks live in `.yoke/doctor/` (`check_*.py`, `hc_*` functions or
  `PROJECT_HEALTH_CHECKS`) and import as `yoke_project_checks`. A module that
  fails to import is a FAIL. The engine roster holds only checks true of every
  project.

## Related

- [Events](events.md)
- [Ouroboros](ouroboros.md)
