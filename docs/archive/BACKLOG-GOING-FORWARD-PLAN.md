# Backlog Going Forward Plan

## Purpose

This is a backlog-operations plan, not a coding plan.

Use it to:

- decide what to merge next
- decide what to thaw, shepherd, split, subsume, or cancel
- decide what should run in parallel
- decide what must be fixed before rerunning the "browser-visible Buzz change"
  experiment

It should not be read as "implement everything in this order" without checking
the live backlog first.

## Section 0 — Backlog Operations To Do Now

This section exists so a backlog operator can make the plan current before any
more implementation work starts.

### 0.1 Merge / Close / Keep As-Is

Do these immediately:

- keep `YOK-906` cancelled
- keep `YOK-920` cancelled

Rationale:

- `904` is already merged/done; its failed deploy was a disposable test-balloon
  outcome and should not distort the queue
- `906` was a task-ordering warning for `YOK-837`, which is already done
- `920` was superseded by `YOK-923`

### 0.2 New Root-Cause Tickets Already Filed

These tickets are the real remediation wave from the failed `YOK-910`
experiment. Do not let them get lost behind older strategic work:

- `YOK-912`
- `YOK-913`
- `YOK-914`
- `YOK-915`
- `YOK-916`
- `YOK-917`
- `YOK-918`
- `YOK-919`
- `YOK-921`
- `YOK-922`
- `YOK-923`
- `YOK-924`

These should be treated as the new top-priority operator queue.

### 0.3 One Additional Ticket — FILED

Filed as `YOK-925`: Browser-testable items must materialize executable
scenarios or substrate checks (GitHub #2207).

### 0.4 Freeze / Thaw Decisions To Apply Now

Apply these decisions now:

- keep the external project onboarding idea parked
- keep `YOK-847` frozen
- keep `YOK-896` unfrozen but parked
- keep `YOK-897` unfrozen but parked

Rationale:

- `629` should wait until one clean external-project browser-change rerun works
- `847` should follow repaired reality, not race ahead of it
- `896` and `897` are valid later follow-ons, but neither should outrank the
  remediation wave

### 0.5 Priority Framing — APPLIED

YOK-918 and YOK-923 bumped to `high` priority (core integrity fixes that must
land before trusting a rerun). YOK-912/913/914 were already `high`.

Wave ordering:

1. deploy-path blockers (high)
   - `912`, `913`, `914`
2. state-truthfulness and recovery (918/923 high, rest medium)
   - `918`, `923`, `917`, `916`, `921`
3. browser-verification truthfulness
   - `922`, `915`, `925`
4. operator guardrails
   - `919`, `924`
5. only after one clean rerun:
   - `629`, optional `897`, optional `896`, then `847`

## Current Backlog Reality

### The Core Platform Wave Is Landed

The major lifecycle, delivery, QA, browser, and environment wave is now in
main:

- `YOK-831` delivery runtime
- `YOK-832` stakeholder progress view and flow-defined done semantics
- `YOK-833` unified QA platform
- `YOK-834` browser QA scenario model
- `YOK-836` visual smoke wiring
- `YOK-837` browser automation substrate
- `YOK-846` explicit QA requirements / browser-default policy
- `YOK-850` hostname-based preview/ephemeral environments
- `YOK-895` baseline image versioning and storage
- `YOK-900` wildcard TLS provisioning
- `YOK-901` remove `tailscale_ip`
- `YOK-902` dynamic reverse proxy config management
- `YOK-903` item_progress_view ownership cleanup
- `YOK-905` annotated screenshot interface-contract cleanup
- `YOK-907` browser-daemon JSON parser hardening
- `YOK-908` remove `merged` from task lifecycle
- `YOK-909` dedup QA requirement seeding on advance to active

This means the next problem is no longer "finish the platform."

The next problem is:

- make one browser-visible Buzz change go idea -> active -> passed -> usher ->
  prod with real browser evidence and truthful state

### Immediate Tail

- `YOK-904` — done
- `YOK-906` — cancelled
- `YOK-920` — cancelled

`YOK-904` is merge-tail cleanup, not a new strategic lane.

### New Root-Cause Wave From The YOK-910 Experiment

These are the new non-frozen root-cause tickets created by the failed
"purple pony login page" experiment:

- `YOK-912` — standalone usher merge blocked by missing
  `YOKE_DONE_TRANSITION=1`
- `YOK-913` — merge-worktree validates branch before resolving cross-project
  repo
- `YOK-914` — ephemeral-verify fails after branch deletion
- `YOK-915` — Buzz CI E2E fails because backend API server is not started
- `YOK-916` — DB errors swallowed by script chain
- `YOK-917` — `in_release` prematurely closes GitHub issues
- `YOK-918` — deploy-pipeline uses raw SQL for item status transitions
- `YOK-919` — lint keyword matching too broad
- `YOK-921` — no documented usher recovery path
- `YOK-922` — browser_smoke can pass without browser evidence
- `YOK-923` — contradictory deployment_run state allowed
- `YOK-924` — subagents lack the schema/column guardrails from CLAUDE.md

### Unfrozen Optional Follow-Ons

- `YOK-896` — cross-project scenario template library
- `YOK-897` — visual regression dashboard

These are not the next priority anymore.

### Frozen / Late

- external project onboarding idea
- `YOK-847` — documentation migration

These should stay frozen until the end-to-end browser-visible external-project
change path works once for real.

## What The Next Successful Rerun Must Prove

For the next "change a visible Buzz page and usher it" experiment to count as a
real success, all of the following must be true:

- the item is classified browser-testable
- browser QA cannot be satisfied by a pure agent/code-review verdict
- a real browser execution occurs
- real evidence exists: screenshot, diff, trace, or equivalent artifact
- usher can merge a standalone Buzz item from the Yoke repo without repo/path
  hacks
- the pipeline can survive branch cleanup and still reach `prod-deploy`
- deployment state cannot be marked `succeeded` while a failed stage is still
  recorded
- the GitHub issue stays open at `in_release` and closes only at `done`
- failures produce actionable error output
- operators have a documented recovery path when pipeline stages fail

If these are not true, the loop is still not closed.

## Critical Observation — RESOLVED

The missing ticket has been filed as `YOK-925`: Browser-testable items must
materialize executable scenarios or substrate checks (GitHub #2207). See the
item body for full acceptance criteria and cold-start context.

## Ticket-By-Ticket Guidance

### `YOK-904`

Status:

- done

Guidance:

- treat it as closed
- ignore the failed deploy as test-balloon noise
- do not spend more planning effort on it afterward

### `YOK-912`, `YOK-913`, `YOK-914`

These are the direct blocker chain for "usher a standalone Buzz item from
Yoke and actually reach deploy."

Guidance:

- treat these as the first real remediation wave
- do not let unrelated optional follow-ons outrank them

### `YOK-918`, `YOK-923`, `YOK-917`, `YOK-916`

These are the state-truthfulness and diagnosability wave.

Guidance:

- they should land before trusting another rerun
- `918` and `923` are the most important of this group

### `YOK-922`, `YOK-915`, `YOK-925`

These are the browser-verification truthfulness wave.

Guidance:

- `922` is mandatory before claiming browser QA is meaningful
- `915` is mandatory if Buzz CI E2E is part of the expected evidence path
- `925` is mandatory if the goal is true automatic substrate-backed
  verification for browser-testable work

### `YOK-921`, `YOK-919`, `YOK-924`

These are operator hardening / ergonomics / guardrail tickets.

Guidance:

- important, but second-tier compared with the deploy-path and browser-evidence
  blockers

### `YOK-896`

Status:

- idea

Guidance:

- keep later
- only thaw if a second real multi-project reuse need exists

### `YOK-897`

Status:

- idea

Guidance:

- keep later
- this is a review UI for visual artifacts after the evidence-producing path is
  already trustworthy
- do not let it outrank the tickets that make those artifacts trustworthy in
  the first place

### External project onboarding idea

Status:

- frozen idea

Guidance:

- do not thaw yet
- the failed experiment shows the external-project productization story is not
  trustworthy enough yet
- thaw only after one clean end-to-end rerun of the Buzz browser-change case

### `YOK-847`

Status:

- frozen idea

Guidance:

- keep last
- documentation should follow the repaired truth, not try to race ahead of it

## Recommended Operator Sequencing

### Wave 0 — Close The Tail

Do immediately:

1. keep `YOK-904` treated as closed
2. keep `YOK-906` cancelled
3. keep `YOK-920` cancelled

### Wave 1 — Make Usher / Merge / Deploy Work For The Real Use Case

Shepherd and execute first:

1. `YOK-912`
2. `YOK-913`
3. `YOK-914`

Recommended parallelism:

- `912` + `913` in parallel
- `914` shepherd in parallel, implement once the merge-path fix direction is
  clear

Why this wave comes first:

- without it, the pipeline still cannot reliably reach production for the exact
  standalone cross-project case you tested

### Wave 2 — Make Deployment State Truthful And Recoverable

Next:

1. `YOK-918`
2. `YOK-923`
3. `YOK-917`
4. `YOK-916`
5. `YOK-921`

Recommended emphasis:

- `918` and `923` are the core integrity fixes
- `917` and `916` make operator-visible state trustworthy
- `921` documents the recovery path once the underlying behavior is fixed

### Wave 3 — Make Browser Verification Real

Then:

1. `YOK-922`
2. `YOK-915`
3. `YOK-925`

Why:

- `922` stops fake browser passes
- `915` fixes Buzz's actual E2E execution path
- `YOK-925` closes the gap between
  "browser-testable got recognized"
  and
  "a real browser check was automatically materialized and executed"

### Wave 4 — Operator Guardrails And Quality Of Life

Then:

1. `YOK-919`
2. `YOK-924`

These matter, but they are not the direct blockers to the rerun.

### Wave 5 — Rerun The Exact Experiment

Only rerun the "browser-visible Buzz change" experiment when:

- `912`, `913`, `914`, `918`, `923`, `917`, `916`, `921`, `922`, `915`
  are done
- and the `YOK-925` is filed and either:
  - done, or
  - explicitly deferred with acceptance that Yoke still will not
    auto-materialize substrate-backed browser checks

### Wave 6 — Resume Strategic Backlog Work

After one clean rerun:

1. revive/shepherd the external project onboarding idea
2. optionally shepherd `YOK-897`
3. keep `YOK-896` later unless reuse pressure is real

### Wave 7 — Final Reconciliation

Finally:

1. thaw and execute `YOK-847`

## Parallelism Cheat Sheet

### Safe Parallel Set Right Now

- `YOK-912`
- `YOK-913`
- `YOK-914` shepherd

### Safe Parallel Set After Wave 1 Is Underway

- `YOK-918`
- `YOK-923`
- `YOK-917`
- `YOK-916`
- `YOK-921`

### Safe Parallel Set For Browser-Truthfulness Work

- `YOK-922`
- `YOK-915`
- `YOK-925`

### Do Not Start As Main Lanes Yet

- external project onboarding idea
- `YOK-897`
- `YOK-896`
- `YOK-847`

## Expected Merge Order

1. `YOK-912`
2. `YOK-913`
3. `YOK-914`
4. `YOK-918`
5. `YOK-923`
6. `YOK-917`
7. `YOK-916`
8. `YOK-921`
9. `YOK-922`
10. `YOK-915`
11. `YOK-925`
12. `YOK-919`
13. `YOK-924`
14. rerun experiment
15. external project onboarding idea
16. optional `YOK-897`
17. optional `YOK-896`
18. `YOK-847`

Notes:

- `912/913/914` are the hard path blockers and should outrank everything else
- `922` is more important than `897`
- `629` should now wait for a real successful rerun, not the other way around

## Quick Rules

- `904` is closed; ignore its failed deploy as test-balloon noise
- Main next wave: `912`, `913`, `914`
- State-truthfulness wave right after: `918`, `923`, `917`, `916`, `921`
- Browser-truthfulness wave after that: `922`, `915`, `925`
- Do not thaw `629` yet
- Do not prioritize `897` over closing the loop
- Keep `847` last
