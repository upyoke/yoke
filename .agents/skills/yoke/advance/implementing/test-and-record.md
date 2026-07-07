# Active — Test Commands & QA Recording

Surfaces project test commands and handles QA run recording after implementation. Called by the active router as the test-and-record phase.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`

**Exact-path test anchor:** Every test invocation in this phase — `pytest`, `python3 -m pytest`, `python3 -m yoke_core.tools.watch_pytest`, and the project-registered four-tier `quick` / `full` / `e2e` / `smoke` commands surfaced below — MUST collect and run from `{WORKTREE_PATH}`, not the main checkout. The Step 0 `cd "{WORKTREE_PATH}"` directive in [`implementation.md`](implementation.md) is what keeps the working directory bound; without it, pytest's positional collection path silently resolves under main and the verification gates run against the wrong tree. `watch_pytest` hard-refuses wrong-cwd invocations under a worktree-bearing claim with a one-line remediation message — `cd` once at the top of the session and the refusal never fires.

---

## a1. Use Project Context Summary

This phase runs after `implementing/project-context.md`. If that earlier phase emitted a `Project Context Summary`, use its likely test/doc surfaces to scope the text-sensitive audit below before widening the grep.

Do not broad-explore a project's test tree when the project docs already name the relevant helpers, fixtures, or directories. Start from the surfaced paths, then expand only as far as the minimum audit scope requires.

## a2. Surface Project Test Commands

After QA seeding, read and surface the project's registered test commands so the implementing agent knows exactly which test suites to run. This uses the same DB-backed project command registry that conduct/dispatch-context.md uses for Engineer and Tester dispatch, so the two surfaces stay consistent.

Project-level test commands live in the `command_definitions` Project Structure
family. In the normal advance flow, use the Project Context Summary emitted by
`implementing/project-context.md`. If that summary is missing, the
`command_definitions` reader is a Yoke source-dev/admin helper with no
registered product CLI wrapper yet; do not present it as an external project
command.

```bash
_item_project=$(yoke items get {N} project 2>/dev/null) || true
_cmd_quick=""
_cmd_full=""
_cmd_e2e=""
_cmd_smoke=""
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 # Source-dev/admin read: populate each value from the command_definitions
 # Project Structure family for scopes quick/full/e2e/smoke.
fi
```

**Four-tier test model:**
- **quick** — fast signal suite (typically unit tests + vitest)
- **full** — everything: quick + build + browser integration tests (mocked APIs)
- **e2e** — real end-to-end against a deployed backend (frontend → backend → DB)
- **smoke** — shallow real-stack subset: "is the system alive and are critical paths working?"

E2E and smoke both exercise a real deployment; browser integration tests live under **full** and mock their APIs. An absent `e2e` scope means "no real E2E tests are configured yet," not "browser integration tests go here."

**Validate configured commands before surfacing.** After reading test commands,
run the source-dev/admin project command validator to detect broken commands
before the agent tries to use them. This validator has no registered product CLI
wrapper yet. It emits `project=<id>` then one
`<scope>=<valid|invalid|empty>|<detail>` line per canonical scope (`quick`,
`full`, `e2e`, `smoke`), returns 0 when nothing is invalid and 1 when at least
one scope is invalid. An empty value is reported as `empty`, not `invalid`:

```bash
# Source-dev/admin validation read: set _validation_output from the project
# command validator for "$_item_project".
_quick_status=$(printf '%s' "$_validation_output" | grep '^quick=' | sed 's/^[^=]*=//; s/|.*//')
_full_status=$(printf '%s' "$_validation_output" | grep '^full=' | sed 's/^[^=]*=//; s/|.*//')
_e2e_status=$(printf '%s' "$_validation_output" | grep '^e2e=' | sed 's/^[^=]*=//; s/|.*//')
_smoke_status=$(printf '%s' "$_validation_output" | grep '^smoke=' | sed 's/^[^=]*=//; s/|.*//')
if [ "$_quick_status" = "invalid" ]; then _cmd_quick=""; fi
if [ "$_full_status" = "invalid" ]; then _cmd_full=""; fi
if [ "$_e2e_status" = "invalid" ]; then _cmd_e2e=""; fi
if [ "$_smoke_status" = "invalid" ]; then _cmd_smoke=""; fi
```

**Always emit this block** — even when commands are empty. Showing "none configured" prevents the agent from guessing CLI invocations. When a command is invalid, show the warning and degrade to "none configured":

```
Project Test Commands (from project registry):
 Quick: {_cmd_quick or "none configured"} {if _quick_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
 Full: {_cmd_full or "none configured"} {if _full_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
 E2E: {_cmd_e2e or "none configured"} {if _e2e_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
 Smoke: {_cmd_smoke or "none configured"} {if _smoke_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
```

**Do NOT use ad-hoc test discovery** (scanning `package.json`, running bare `npx vitest` or `npx playwright test`). Always prefer the project-registered commands.

**E2E and smoke guidance for standalone items:** If `_cmd_e2e` is non-empty, the implementing agent MUST run the E2E suite before recording AC-verification QA runs when the changes are E2E-sensitive. The same rule applies to `_cmd_smoke` when the changes are smoke-sensitive (e.g., touching deploy-critical paths, auth, or homepage routes). If the agent determines the changes are not E2E- or smoke-sensitive, it MUST record a brief waiver in the QA run's `--raw-result` explaining why the suite was skipped.

## a2b. Quick/Full Command Failure Discipline

When the `quick` or `full` scope is configured and the implementing agent runs it, the **entire** configured command must be accounted for. Partial success is not blanket success.

**If any part of the registered command fails**, the agent MUST do one of:
1. **Fix the failure** and re-run until the full command passes, OR
2. **Record a failing QA run** (`--verdict "fail"`) with the failure details in `--raw-result`, OR
3. **Record an explicit waiver** — a passing QA run whose `--raw-result` explains why the failure is not attributable to the current change.

**The agent MUST NOT:**
- Silently drop the failing portion and run only the passing subset without recording a waiver.
- Record a blanket pass result that implies the full registered command succeeded when only a subset was run.
- Substitute an ad-hoc subset command without documenting the deviation.

**Waiver format:** Use `--verdict "pass"` with `--raw-result` that begins with `"Waiver:"` followed by: (a) what failed, (b) why it is not caused by the current change, and (c) a YOK-N reference to the tracking ticket for the pre-existing failure if one exists.

**Path-claim ownership is not a waiver:** Future/planned item ownership or a planned path claim does not make a registered command failure pre-existing. If fixing the failure touches a file outside the active claim, widen the claim and encode the serial dependency or claim reconciliation first. Do not use `path-claim-override` for a planned future claim when dependency or claim reconciliation can resolve the ordering; override is last resort for irreducible live collisions and requires explicit operator approval.

## a3. Text-Sensitive Test Audit Gate

**Conditional step — only when the change touches user-visible copy, theme strings, button labels, empty/error state messages, route-specific page wording, or similar UI text.** Skip entirely for backend-only, script-only, config-only, or non-copy changes.

This is a **structural gate**, not advisory guidance. The gate has two enforcement points: a deterministic pre-edit preflight and a blocking pre-commit verify step. Both are mandatory when the change is text-sensitive.

### a3.1. Discover test surfaces (before first edit)

Run the preflight helper before writing any implementation code:

```bash
# Source-dev/admin stale-string preflight helper: set _audit_json for
# YOK-{N} and "{WORKTREE_PATH}". No registered product CLI wrapper exists yet.
```

The helper consumes the same project config (the `context_routing` Project Structure family's `testing` topic plus the `e2e` and `smoke` scopes of the `command_definitions` family) that `implementing/project-context.md` reads, falls back to deterministic directory discovery, derives candidate old strings, and greps the discovered test surfaces in one pass.

Candidate-string derivation prefers **removed lines of the combined git diffs** (`git diff`, `git diff --staged`, `git diff main...HEAD`) so mid-implementation runs target the literal values being replaced. When no removals exist yet (preflight, before any edit), it falls back to quoted literals in the item spec/body and filters out anything that also appears on a `+` line — so new values the agent intentionally placed are never flagged as stale.

Surface the JSON summary to the agent. The important fields are:
- `project`, `source`, `surfaces`, `doc_paths`
- `candidate_strings` — the old values being audited
- `candidate_source` — `git_diff_removed`, `spec_body`, or `none`
- `matches` — pre-edit stale references that must be fixed in the same implementation commit
- `verdict` — one of `not_text_sensitive`, `missing_candidate_strings`, `clean`, `matches_found`

### a3.2. Handle the preflight verdict

**If `verdict` is `matches_found`:** Surface the matches as a **mandatory checklist**. The agent MUST fix every matched file during implementation — not after commit. Display:

```
## Stale String Audit — Pre-Edit Matches

The following test files reference strings being changed. Fix these IN the same commit as the implementation, not after:

- {file}:{line} — "{matched content}"
- ...

Total: {N} match(es) in {M} file(s). All must be updated before commit.
```

**If `verdict` is `clean`:** Record that explicitly:
```
Stale String Audit: no pre-existing references found in test surfaces. Proceeding.
```

**If `verdict` is `not_text_sensitive`:** Record the skip:
```
Stale String Audit: skipped (not text-sensitive).
```

**If `verdict` is `missing_candidate_strings`:** Stop and tighten the ticket context before coding. Add explicit quoted old strings to the spec/body (or otherwise clarify the values being replaced), then re-run the preflight. The gate must know what old strings it is enforcing before implementation begins.

### a3.3. Pre-commit verify (blocking gate)

**Before every commit** that includes implementation changes for a text-sensitive item, run the blocking verify helper:

```bash
# Source-dev/admin stale-string verify helper for YOK-{N} and
# "{WORKTREE_PATH}". No registered product CLI wrapper exists yet.
```

`advance/finalize.md` step 9 re-runs this helper automatically for the review-completion commit path (`reviewing-implementation` / `reviewed-implementation`), so the normal `/yoke advance` flow now blocks stale-string commits structurally.

**If exit code is 1 (matches found):** Do NOT commit. Fix the remaining stale strings first, then re-run the verification. This is a hard block — there is no override flag.

**If exit code is 2 (candidate extraction failure):** Do NOT commit. Tighten the item spec/body so the old strings are explicit, then re-run the preflight and verification.

The agent covers all file types in test directories — `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.py` — not just `*.spec.*` or `*.test.*` patterns. This ensures helper files (`api-mocks.ts`), smoke-specific files (`smoke.spec.ts`), fixtures, and shared utilities are all caught.

---

## a4. DB Mutation Evidence — authoritative-DB apply for exception-pathway modules

If the item declares `mutation_intent="apply"` with one or more entries in `migration_modules` (see the `db_mutation_profile` JSON-nested-field schema in your packet), the `check_implementing_to_reviewing_implementation_gate` requires a completed migration-audit row keyed on each module name **on the model's authoritative DB**, not the worktree's validation surface. The authoritative DB is declared by the project's `migration_model` capability; for Yoke's `primary` model it is the connected Postgres authority.

**Governed-runner modules** (runner kind = `governed_migration_module`): rehearse and live-apply go through the standard contract.

- **Projects whose deployment flow declares a `migration_apply` lifecycle hook** (e.g. Buzz prod): the live-apply happens automatically during that phase. No extra step.
- **Projects without that hook** (e.g. Yoke's `primary` model itself when iterating from inside `/yoke advance`): the agent runs the apply manually before advancing past `implementing`:

  The `migration_apply` governed runner is a Yoke source-dev/admin boundary,
  not a product CLI wrapper. Read its `rehearse` and `live-apply` help epilogs
  before running either subcommand.

  Read the temporary pre-ephemeral Yoke self-migration recipe in the help epilog before running the commands. The short shape is: back up prod Aurora, provision a separate validation-only DB, set **only** `YOKE_PG_DSN_VALIDATION`, run `rehearse`, stop for the operator checkpoint, then run `live-apply`. Never point `YOKE_PG_DSN` at the validation DB. For an unmerged worktree module, pass the same `--module-path-override <worktree>/runtime/api/domain/migrations/<slug>.py` to both commands.

  **Commit the migration module BEFORE `live-apply`.** When all declared modules reach `migration_audit.state='completed'` on the authoritative DB, the runner calls `yoke_core.domain.migration_auto_retire.auto_retire_after_live_apply`, which stages `git rm` for the module file plus its sibling `test_<identifier>.py` (single-install topology only). Untracked module files cannot be staged — the auto-retire path emits `MigrationModuleRetired` with `outcome=no_op` and `reason="module_file_not_in_git"`, and the agent has to do the `git rm` manually. The expected sequence is: **commit the module → live-apply → one finalize commit picks up the staged deletion**. The advance/polish finalize step's `git add -A` + commit picks the staged deletion up automatically.

  **Avoid recursive `rehearsal_commands` self-calls.** The attestation's `rehearsal_commands` list is re-executed inside the rehearse runner against the validation surface. A command that invokes the `migration_apply` rehearse/live-apply runner would recurse into the same runner with the validation DB bound (where the items row does not exist) and die mid-rehearse. Use focused module-surface checks instead: a schema-table probe appropriate to the validation surface, a pytest run against the module's own test file, or similar. The refine-time dryrun (`yoke_core.domain.attestation_rehearsal_dryrun`) now flags this shape as `recursive_migration_apply_self_call`.

**Exception-pathway modules** (modules that call `record_audit_fingerprint` instead of going through the governed runner): the apply is the author's responsibility. Before calling `/yoke advance YOK-{N} reviewing-implementation`, run the module's apply CLI against **both** surfaces:

```bash
# 1. Validation surface (worktree-local). Use the module's explicit
# validation-target option/env; do not point Yoke authority at a DB file.
# Source-dev/admin exception module apply CLI for the declared module.

# 2. Authoritative DB. Run without a DB-path override so the module uses
# the active Postgres authority selected by the backend.
# Source-dev/admin exception module apply CLI for the same declared module.

# 3. Confirm the audit row landed on authoritative (not just validation):
python3 -m yoke_core.cli.db_router query \
 "SELECT state, exception_reason FROM migration_audit \
  WHERE migration_name='<module>'"
```

Only after the authoritative row is present is the one-shot cutover code safe to delete. Deleting earlier (after validation-surface apply alone) leaves the ticket with no path past `implementing` without reconstructing the module from git history.

## b. Record QA Runs (after implementation, before advance done)

After completing implementation and running tests/verification, record a `qa_runs` entry for each requirement:

```bash
# Record a passing run:
yoke qa run add \
 --requirement-id {req-id} \
 --executor-type "agent" \
 --qa-kind "ac_verification" \
 --verdict "pass" \
 --raw-result "{brief evidence — e.g., 'All 12 tests pass', 'Config verified in output'}"
```

If a test fails, record `--verdict "fail"` with brief failure details in `--raw-result`. For multi-line file evidence, summarize the relevant excerpt or attach an artifact through the registered QA artifact surfaces; the old DB-router `qa run-add --raw-result-file` helper is operator-debug only, not normal product flow. Fix the issue, then record a new passing run.

## Evidence-Based Summary Discipline

When summarizing test results, the agent MUST derive all claims from recorded evidence (QA runs, actual command output, recorded waivers). Specifically:

- **Test count claims** MUST match actual command output. Do not extrapolate or round.
- **Suite scope claims** MUST reflect which suites were actually run.
- **Never claim success for a suite that was not run or that failed.**

**IMPORTANT — browser-kind requirements:** For `browser_smoke` and `browser_diff` requirements, do NOT record `executor_type='agent'` runs. These kinds require `executor_type='browser_substrate'` and must come from `yoke qa browser run`. Browser QA execution happens automatically via the pre-implemented gate in `advance/browser-qa.md`.

## c. Advance Through Review Completion

**Test pass is not reviewed-implementation gate satisfaction.** Passing the registered test suite (the four-tier `quick`/`full`/`e2e`/`smoke` commands surfaced in section a2) means the implementation behaves as expected. The reviewed-implementation gate (run by the advance to `reviewed-implementation`) checks something different: every blocking `qa_requirements` row for the item must have a passing `qa_runs` entry recorded. Both must hold. While the test suite is green but you have not yet recorded the AC verification runs (or routed through the advance), do **not** summarize work as "all gates pass" — say "tests pass" instead. To preview the gate verdict at any point, use the registered summary surface: `yoke qa gate-summary --item YOK-N --target reviewed-implementation` for a standalone issue, or `yoke qa gate-summary --epic-id <epic_id> --task-num <task_num> --target reviewed-implementation` for an epic task. The gate verdict is the authority; tests being green is necessary but not sufficient.

After recording QA runs for all AC-verification requirements, the issue-workflow-type progression should move through two distinct review states:

1. Advance to `reviewing-implementation` when coding + self-verification are complete and the branch is ready for a deliberate review pass.
2. Stay in the same worktree while performing that review. Fix anything the review finds, re-run relevant verification, and only then run `/yoke advance YOK-{N} reviewed-implementation` — this routes through the full phase dispatch (browser QA, project E2E) before the status update.

**CRITICAL:** The ONLY way to advance to `reviewed-implementation` is via `/yoke advance YOK-{N} reviewed-implementation`. NEVER use `items update N status reviewed-implementation` directly — even if you already ran browser QA and E2E manually. The advance skill handles claim handoff (`handoff-to-polish`), worktree-scoped commit, and lifecycle event emission that raw `items update` skips entirely.

**Commit invariant:** The advance to `reviewed-implementation` must not leave the worktree dirty. Finalize step 9 handles this: when `WORKTREE_PATH` is set, it stages worktree changes (`git -C "$WORKTREE_PATH" add -A`) before checking the index. Review-loop fixes, including newly created files, are committed as part of the advance. Do not rely on manual staging between review fixes and the advance call.

During an autonomous `/yoke advance YOK-{N} implementation` run, do **not** pause for operator confirmation between these states. Continue the review/fix/verify loop in the same session until the item reaches `reviewed-implementation` or you hit a real blocker that prevents further progress.

`reviewed-implementation` is the terminal state for the advance skill itself. Stop the inner advance flow here: do **not** invoke `/yoke polish`, `/yoke usher`, or any other command from inside the advance prose; polish is a fresh command entrypoint that must claim the item itself. Do **not** skip from `reviewing-implementation` directly to `implemented`.

When the advance reaches `reviewed-implementation` inside a routed `/yoke do` chain, return to the loop's chain decision step (`/yoke do` Step C) so it can re-offer (typically into polish). When the advance is invoked directly by the operator outside `/yoke do`, emit the next-step guidance from finalize and stop the turn.

## d. The done-gate checks these automatically

When `advance done` is called, the done-transition engine calls `check_done_gate()`. Use `--skip-qa` to bypass for genuinely trivial items.

## e. Ad-hoc Tester Dispatch

When the implementing agent needs to dispatch a Tester outside the conduct pipeline, it MUST use the structured dispatch template at `.agents/skills/yoke/shared/tester-dispatch-template.md`. **Do NOT dispatch a Tester for browser-kind QA requirements** — those are handled automatically by `advance/browser-qa.md`.
