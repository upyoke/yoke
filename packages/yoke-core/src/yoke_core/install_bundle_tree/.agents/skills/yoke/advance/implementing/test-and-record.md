# Active — Test Commands & QA Recording

Surfaces project test commands and handles QA run recording after implementation. Called by the active router as the test-and-record phase.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`

**Exact-path test anchor:** Every direct test invocation in this phase MUST
collect from `{WORKTREE_PATH}`, not the main checkout. Attached Command cases
resolve the same mapped worktree through `yoke qa case run`; do not re-run
their shell text from another checkout.

---

## a1. Use Project Context Summary

This phase runs after `implementing/project-context.md`. If that earlier phase emitted a `Project Context Summary`, use its likely test/doc surfaces to scope the text-sensitive audit below before widening the grep.

Do not broad-explore a project's test tree when the project docs already name the relevant helpers, fixtures, or directories. Start from the surfaced paths, then expand only as far as the minimum audit scope requires.

## a2. Surface and run attached plan cases

After QA seeding, materialize the default plan for the next verification
checkpoint, then list the item's immutable case snapshots:

```bash
yoke qa plan materialize --item "PREFIX-{N}" \
 --transition reviewing-implementation
yoke qa requirement list --item "PREFIX-{N}" --json
```

Surface every row with a non-null `plan_id`, including its case key, method,
instructions, expected outcome, transition, and host baseline. An empty list
means no project or item plan is attached; do not guess a replacement command.

Run the complete materialized roster through the ordered plan executor:

```bash
yoke qa plan run --item "PREFIX-{N}" \
 --transition reviewing-implementation
```

The method owns execution: Command uses the mapped worktree and exit-code
verdict, Browser check uses automatic assertions, and Browser inspection
captures evidence for agent review. Never extract `method_config.command` and
run it separately, discover a substitute from `package.json`, or replace a
failing case with a smaller command. Use `yoke qa case run` only to rerun a
specific failed deterministic case after diagnosis; inspection verdicts come
from the plan-level review bundle.

**The plan run is the one full execution.** Iterate as much as the work needs
with the cheap layers — the individual failing tests, the changed module's
paths, `yoke watch pytest --impacted main --bounded` (which reports an
unbounded selection instead of widening to the full sweep, so read that verdict
as *keep testing what you judge relevant*) — then let the plan/case run close
the loop. Do not run the project's full sweep by hand and then hand the same
tree to the executor: it re-runs the identical registered command, so only the
verdict-producing run needs to happen. Command execution streams live to
stderr and names its raw capture file before starting, so a long run is
followable without a second copy. Re-running after the tree changes — a fix, a
new commit, the post-rebase run — is a different execution and stays required.

Exit `12` and `state="awaiting_agent_review"` are a mandatory continuation,
not a human-review state. Immediately dispatch the returned
`review_bundle.dispatch` descriptor through the harness subagent facility,
passing its prompt and complete immutable bundle to the named
`subagent_type`. The reviewing agent inspects every transcript and visual,
then sends exactly one complete verdict batch through the returned
`submit_command`. Do not continue lifecycle work, ask a human, waive the cases,
or recapture evidence because the reviewer dispatch is pending. Only an
agent verdict of `inconclusive` creates a human Inbox request.

## a2b. Plan-case failure discipline

Every attached case must end in pass, waiver, or an explicit review outcome.
If a case fails, fix the failure and rerun the same requirement, or use the
registered waiver surface with a concrete rationale. Future/planned item ownership
or a planned path claim is not a waiver for a current regression.
If the fix expands the required files, widen the claim and use
dependency or claim reconciliation before retrying.
Do not use `path-claim-override` for a planned future claim when reconciliation can
resolve the ordering; override is last resort for irreducible live collisions
and requires explicit operator approval.

## a3. Text-Sensitive Test Audit Gate

**Conditional step — only when the change touches user-visible copy, theme strings, button labels, empty/error state messages, route-specific page wording, or similar UI text.** Skip entirely for backend-only, script-only, config-only, or non-copy changes.

This is a **structural gate**, not advisory guidance. The gate has two enforcement points: a deterministic pre-edit preflight and a blocking pre-commit verify step. Both are mandatory when the change is text-sensitive.

### a3.1. Discover test surfaces (before first edit)

Run the preflight helper before writing any implementation code:

```bash
# Source-dev/admin stale-string preflight helper: set _audit_json for
# PREFIX-{N} and "{WORKTREE_PATH}". No registered product CLI wrapper exists yet.
```

The helper consumes project context plus attached QA-plan case configuration,
falls back to deterministic directory discovery, derives candidate old strings,
and greps the discovered test surfaces in one pass.

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

**If `verdict` is `missing_candidate_strings`:** Stop and tighten the work-item context before coding. Add explicit quoted old strings to the spec/body (or otherwise clarify the values being replaced), then re-run the preflight. The gate must know what old strings it is enforcing before implementation begins.

### a3.3. Pre-commit verify (blocking gate)

**Before every commit** that includes implementation changes for a text-sensitive item, run the blocking verify helper:

```bash
# Source-dev/admin stale-string verify helper for PREFIX-{N} and
# "{WORKTREE_PATH}". No registered product CLI wrapper exists yet.
```

`advance/finalize.md` step 9 re-runs this helper automatically for the review-completion commit path (`reviewing-implementation` / `reviewed-implementation`), so the normal `/yoke advance` flow now blocks stale-string commits structurally.

**If exit code is 1 (matches found):** Do NOT commit. Fix the remaining stale strings first, then re-run the verification. This is a hard block — there is no override flag.

**If exit code is 2 (candidate extraction failure):** Do NOT commit. Tighten the item spec/body so the old strings are explicit, then re-run the preflight and verification.

The agent covers all file types in test directories — `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.py` — not just `*.spec.*` or `*.test.*` patterns. This ensures helper files (`api-mocks.ts`), smoke-specific files (`smoke.spec.ts`), fixtures, and shared utilities are all caught.

---

## a4. DB Mutation Evidence — authoritative-DB apply for exception-pathway modules

If the item declares `mutation_intent="apply"` with one or more entries in `migration_modules` (see the `db_mutation_profile` JSON-nested-field schema in your packet), the `check_implementing_to_reviewing_implementation_gate` requires a completed migration-audit row keyed on each module name **on the model's authoritative DB**, not the worktree's validation surface. The authoritative DB is declared by the project's `migration_model` capability; for Yoke's `primary` model it is the connected Postgres authority.

**Governed-runner modules** (runner kind = `governed_migration_module`):

  **Rehearse, then merge. You do not apply.** Run
  `yoke migration rehearse PREFIX-{N}` from a local-Postgres or matching
  db-admin connection. The command refuses HTTPS product connections because
  it executes the checked-out project's code and validation surface locally.
  Rehearsal runs the module
  against the model's validation surface and records the receipt the evidence
  gate reads. Applying to the authoritative database is the job of the boot
  converge that starts a server running your merged code — there is no
  authoritative apply step for you to run or wait on.

  **The module is permanent.** Add it to the ordered history as
  `NNNN_slug.py`, commit it, and leave it there forever. It is never deleted
  after applying; a module that is gone cannot be applied by a universe that
  never received it, which is exactly how installs used to diverge silently.
  The body must be safe to re-run and must NOT commit — the applier commits
  each entry together with its ledger row, which is what makes "applied but
  unrecorded" impossible.

  **Avoid recursive `rehearsal_commands` self-calls.** The attestation's
  commands run inside rehearsal against the validation surface. A command
  that invokes `yoke migration rehearse` would recurse. Use a focused schema
  probe or the module's tests instead; refine-time dry-run rejects recursive
  rehearsal commands.

**Exception-pathway modules** (modules that call `record_audit_fingerprint` instead of going through the governed runner): the apply is the author's responsibility. Before calling `/yoke advance PREFIX-{N} reviewing-implementation`, run the module's apply CLI against **both** surfaces:

```bash
# 1. Validation surface (worktree-local). Use the module's explicit
# validation-target option/env; do not point Yoke authority at a DB file.
# Source-dev/admin exception module apply CLI for the declared module.

# 2. Authoritative DB. Run without a DB-path override so the module uses
# the active Postgres authority selected by the backend.
# Source-dev/admin exception module apply CLI for the same declared module.

# 3. Confirm the audit row landed on authoritative (not just validation):
yoke db read --format lines \
 "SELECT state, exception_reason FROM migration_audit \
  WHERE migration_name='<module>'"
```

The exception module and its verification remain tracked as durable history.
An audit row proves one execution; it does not prove every present or future
install has received the change, and therefore never authorizes deleting the
only executable record.

## b. Record QA Runs (after implementation, before advance done)

After completing implementation and running tests and verification, record a `qa_runs` entry for each requirement:

```bash
# Record a passing run:
yoke qa run add \
 --requirement-id {req-id} \
 --performed-by "agent" \
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

**IMPORTANT — Browser method cases:** Do not record an `agent` verdict for
`browser-check` or `browser-inspection`. Execute the requirement through
`yoke qa case run`; the registered `browser_substrate` executor records its
own provenance and evidence.

## c. Advance Through Review Completion

**One plan-case pass is not union-gate satisfaction.** Every blocking
requirement in the attached plan must pass or be waived. To preview the union,
use `yoke qa gate-summary --item PREFIX-N --target reviewed-implementation` for a
standalone issue, or the epic/task form for a task lane. The gate verdict is
the authority.

After recording QA runs for all AC-verification requirements, the pinned
advance workflow moves through two distinct review stages:

1. Advance to `reviewing-implementation` when coding + self-verification are complete and the branch is ready for a deliberate review pass.
2. Stay in the same worktree while performing that review. Fix anything the review finds, re-run relevant verification, and only then run `/yoke advance PREFIX-{N} reviewed-implementation` — this routes through the full phase dispatch (browser QA, project E2E) before the status update.

**CRITICAL:** The ONLY way to advance to `reviewed-implementation` is via `/yoke advance PREFIX-{N} reviewed-implementation`. NEVER use `items update N status reviewed-implementation` directly — even if you already ran browser QA and E2E manually. The advance skill handles claim handoff (`handoff-to-polish`), worktree-scoped commit, and lifecycle event emission that raw `items update` skips entirely.

**Commit invariant:** The advance to `reviewed-implementation` must not leave the worktree dirty. Finalize step 9 handles this: when `WORKTREE_PATH` is set, it stages worktree changes (`git -C "$WORKTREE_PATH" add -A`) before checking the index. Review-loop fixes, including newly created files, are committed as part of the advance. Do not rely on manual staging between review fixes and the advance call.

During an autonomous `/yoke advance PREFIX-{N} implementation` run, do **not** pause for operator confirmation between these states. Continue the review/fix/verify loop in the same session until the item reaches `reviewed-implementation` or you hit a real blocker that prevents further progress.

`reviewed-implementation` is the terminal state for the advance skill itself. Stop the inner advance flow here: do **not** invoke `/yoke polish`, `/yoke usher`, or any other command from inside the advance prose; polish is a fresh command entrypoint that must claim the item itself. Do **not** skip from `reviewing-implementation` directly to `implemented`.

When the advance reaches `reviewed-implementation` inside a routed `/yoke do` chain, return to the loop's chain decision step (`/yoke do` Step C) so it can re-offer (typically into polish). When the advance is invoked directly by the operator outside `/yoke do`, emit the next-step guidance from finalize and stop the turn.

## d. The done-gate checks these automatically

When `advance done` is called, the done-transition engine calls `check_done_gate()`. Use `--skip-qa` to bypass for genuinely trivial items.

## e. Ad-hoc Tester Dispatch

When the implementing agent needs to dispatch a Tester outside the conduct
pipeline, it MUST use the structured dispatch template at
`.agents/skills/yoke/shared/tester-dispatch-template.md`. Do not dispatch a
Tester for Browser method cases; execute them through the shared case runner.
