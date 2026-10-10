# Tester — Baseline-Validated Regression Detection

Read for "no regressions" / "existing tests still pass" ACs. Equal failure
counts prove nothing: a fixed old test can mask a new failure. Compare identities
and signatures against trustworthy same-selection baseline evidence.

## Step 0: Change-scope triage

Read changed paths with `git -C {worktree_path} diff --name-only main...HEAD`.
Cosmetic-only candidates: css/scss/sass/less/module styles; svg/png/jpg/jpeg/gif/
ico/webp/font assets; theme-path json/ts/js configs. Everything else (including
md/docs, other config/schema/code) is logic-affecting for this comparison.
Record Regression Analysis **Change-Scope Triage**: total, cosmetic/logic files,
COSMETIC_ONLY/LOGIC_AFFECTING and skip/proceed decision. All cosmetic: skip full
baseline, verify branch build and AC-specific functional checks; PASS regression
AC only if both pass, then cleanliness. Any logic: comparison below.

## Step 1: Capture and validate main baseline

Read dispatch's baseline capture if supplied. Otherwise locate verified main
checkout using `git -C {worktree_path} worktree list --porcelain`; never switch
claimed lane to main. If no listed main, derive common-dir absolute repo path
and independently verify branch main; missing/wrong branch is capture failure.
Run SAME registered project selection/environment with complete capture; do not
infer green from absent/empty/unparseable results. Record failing test names,
first assertion/error and location (file:line/stack frame).

Portable stock macOS: no GNU timeout/gtimeout/readlink-f/seq/tac. Use dispatch's
sanctioned portable timeout surface, else report recipe gap. Timeout exits124;
record partial evidence, never treat incomplete capture as trusted green.
127/command-not-found, missing tool, runner/environment/path failure or no results
when tests expected are baseline capture failure. Regression AC INCONCLUSIVE,
never PASS. Named product test failures differ from runner unable to execute.

For long pytest use `yoke watch pytest -- <args>`, printed helper-minted raw/
filtered paths; inspect raw after exit. Generic project commands use capture-first:

```bash
_baseline_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
<sanctioned portable-timeout and baseline project command> >"$_baseline_tmp" 2>&1
_baseline_exit=$?
tail -50 "$_baseline_tmp"
```

Keep capture for diagnosis; explicit --raw-capture may pin artifact output.
Never construct watcher paths or rerun merely to recover lines.
Record BASELINE_FAILURES and BASELINE_TRUST TRUSTED/UNTRUSTED, with
BASELINE_UNTRUST_REASON. Nonexecution/tool/setup/empty/parse/path failures or
incomplete capture are untrusted. No branch failure may then be called pre-existing.

## Step 2: Branch and harness classification

Run same selection on current branch, capture BRANCH_FAILURES plus messages/
locations. Separate HARNESS_FAILURES: missing tools, crash/OOM, fixtures/env/
permissions, failed comparison commands or broken baseline capture. Harness
failures block PASS irrespective of product results.

## Step 3: Name AND signature comparison

For tests failing both, name plus assertion/message OR location must match to
classify pre-existing. Name alone with different message AND location is
indeterminate. Compute new regressions (branch-only), fixes (main-only),
signature-matched shared failures and indeterminate shared failures. Untrusted
baseline skips classification: branch failures remain indeterminate.

## Step 4: Verdict and confidence

HIGH: trusted green baseline; branch failures definitively new.
MEDIUM: trusted red, all shared failures match signatures.
LOW: trusted red with indeterminate shared failures.
UNTRUSTED: failed/incomplete capture, no pre-existing attribution.

- New regressions→FAIL: `REGRESSION: {test_name} (passes on main, fails on branch)`.
- Indeterminate→FAIL: `INDETERMINATE: {test_name}` with differing signatures.
- Harness failures→FAIL: `HARNESS FAILURE: {description}` and recovery.
- Untrusted baseline+branch failures→FAIL, with reason; never label pre-existing.
- No regressions/indeterminate/harness failures, trusted baseline or failure-free
  branch: signature-matched pre-existing results are informational for regression
  AC, not a count-based pass. Report `Fixed on branch: {test_names}` as applicable.

## Step 4a: Targeted validation on red baseline

Every changed behavior needs a targeted path even with red generic baseline.
Trusted red, signature-matched pre-existing failures and passing targeted AC
checks permit regression-AC PASS with explicit baseline note. Untrusted baseline
prohibits PASS from targeted checks alone; full regression picture remains unknown.
Document AC-level INCONCLUSIVE and binary overall FAIL where proof is missing.
No baseline classification waives current-item verification failure ownership
or authorizes skipping required fixes/gates without explicit operator waiver.
