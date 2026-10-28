# Doctor

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Operations](index.md) > Doctor
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

The `stale-remote-branches` check inspects only the selected project's remote
branches. Without its checkout it reports N/A; HTTPS retries on the client,
where missing direct database authority also remains N/A. It matches branch
names to item references and recorded lanes in one query. Under `--fix`, it
fetches once per project and deletes only branches of done or cancelled items
without active registered worktrees, after proving idle cleanup authority and
merged content. A leased delete preserves concurrent remote changes. Branches
with registered worktrees report “lane sweep owns it”; the relay retires their
remote branch, worktree and local branch together.

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
configuration. In an active agent session, the session check requires both
registration and confirmed hook delivery; in an ordinary terminal, the install
roster reports that check N/A with `session_required`. The other install checks
still run normally. Full-corpus audits remain in the full Doctor selection.
For a packaged local dashboard, the served build comes from source-commit metadata
owned by the package serving its assets. Missing or inconsistent metadata leaves
the build unverified; restart advice never certifies an unidentified package.
A stopped local dashboard reports N/A.

Outside an agent session, ordinary Doctor runs (including `--quick`) report
session hook registration, harness sign-in and unattended posture as N/A with
`session_required`. The health receipt shown by `yoke status` retains these
skips. Explicit `--session` or `--only` selections still require
registration and posture evidence and fail when that evidence is missing.
Missing harness CLIs and unverified CLI sign-in report WARN in both the session
and install rosters; these warnings allow setup readiness and onboarding.
Before launching workers, follow the warning's install or login step. The
resolver checks PATH and bundled CLIs, including ChatGPT.app and versioned
Claude Desktop and VS Code binaries; versioned directories stay out of shell
PATH blocks. A launch with a missing CLI refuses as `surface_absent`; a relay
reading of `stale_credential` refuses as `harness_signed_out`, with recovery.
Other quota-reading failures do not establish that a harness is signed out.

Before onboarding, check only the session you are in:

```bash
yoke doctor run --session
```

This checks that the session is registered with confirmed hook delivery, and
that its own harness CLI is signed in and runs `yoke` without approval
prompts. Other installed harnesses do not block it. Agent setup ends with this
check and `/yoke onboard` runs it first.

The session posture check reads the active mode for its registered surface:

- Claude CLI, Desktop and VS Code read the latest parent-session hook's
  `permission_mode`. Only `bypassPermissions` passes. Another mode fails with
  `HARNESS_POSTURE_RESTRICTED`; no readable record fails with
  `HARNESS_POSTURE_UNVERIFIED`: send any prompt in this chat, then rerun.
- Codex CLI and Desktop read the newest native turn's permission metadata;
  only `never` plus `danger-full-access` passes. Missing or unreadable evidence
  fails; rerun in a new turn after it is saved.
- Cursor CLI reads its config. Cursor Desktop and Codex VS Code report
  `HARNESS_POSTURE_CONFIRM_REQUIRED` as a WARN, naming the setting to confirm.
  Onboarding may continue once the person confirms it.

An unknown surface fails. Machine-wide doctor and setup still read saved
configuration; it does not prove a session's active mode. A command allow entry
cannot substitute for an unattended mode. Setup and repair overwrite prompting
modes on every installed harness.

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
