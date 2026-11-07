# Tester — Baseline-Validated Regression Detection

Read for a "no regressions" or "existing tests still pass" criterion. Equal
failure counts prove nothing: a fixed old test can hide a new failure. Compare
test identities and failure signatures against a trusted baseline from the
same selection.

## Step 0: Change-scope triage

List changed files with `git -C {worktree-path} diff --name-only main...HEAD`.
Only style sheets, image and font assets, and theme configs are cosmetic;
everything else, Markdown included, affects logic. Record the counts and the
decision under **Change-Scope Triage**. All cosmetic: skip the baseline, check
the branch build and the criterion's functional checks, and pass the criterion
only if both pass. Otherwise continue.

## Step 1: Main baseline

Use the dispatched baseline capture if one is given. Otherwise find the main
checkout with `git -C {worktree-path} worktree list --porcelain` and confirm it
is on `main`; never switch the claimed lane to main. Run the same selection in
the same environment, capture it whole, and record each failing test with its
first assertion or error and its location.

The baseline is **UNTRUSTED** when the run did not execute or finish: a
timeout, a missing tool or command, a runner, environment or path failure, an
unparseable or empty result where tests were expected. Record the reason. An
untrusted baseline makes the criterion INCONCLUSIVE and no branch failure may
be called pre-existing.

## Step 2: Branch run

Run the same selection on the branch and record failures the same way. Keep
harness failures (missing tools, crashes, fixture, environment or permission
errors) apart from product failures; a harness failure blocks PASS.

## Step 3: Compare names and signatures

A test failing on both sides is pre-existing only when its name and its
message or location match. A matching name with a different message and
location is indeterminate. Branch-only failures are regressions; main-only
failures are fixes.

## Step 4: Verdict

- Regression → FAIL: `REGRESSION: {test_name} (passes on main, fails on branch)`.
- Indeterminate → FAIL: `INDETERMINATE: {test_name}` with both signatures.
- Harness failure → FAIL: `HARNESS FAILURE: {description}` with the recovery.
- Untrusted baseline with branch failures → FAIL, with the reason.
- Otherwise the criterion can pass; list signature-matched pre-existing
  failures as information and `Fixed on branch: {test_names}`.

State confidence: HIGH (trusted green baseline), MEDIUM (trusted red, all
shared failures matched), LOW (trusted red with indeterminate shared failures),
UNTRUSTED.

A red baseline does not excuse unverified changes: every changed behavior still
needs a passing targeted check. With an untrusted baseline, targeted checks
alone cannot pass the criterion.
