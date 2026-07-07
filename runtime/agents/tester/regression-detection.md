# Tester — Baseline-Validated Regression Detection

Reference content for the canonical tester prompt at `runtime/agents/tester.md`. Read and follow this file when the task acceptance criteria include "no regressions" or "existing tests still pass." Do NOT simply compare failure counts between main and the branch — failure counts can match by coincidence when a pre-existing failure is fixed while a new regression is introduced.

This procedure is `Step 5a` in the canonical tester process; the canonical prompt branches to it after running the project's tests in step 5 (or skipping ahead from the change-scope triage when classification is `LOGIC_AFFECTING`).

## Step 0: Change-scope triage

Inspect the changed files to determine whether baseline capture is warranted. This prevents heavyweight builds for changes that cannot cause logic regressions.

**a. Collect changed files:**
```bash
cd {worktree_path}
_changed_files=$(git diff --name-only main...HEAD 2>/dev/null)
```

**b. Classify each changed file.** A file is **cosmetic-only** if its extension matches one of these patterns:
- Style files: `.css`, `.scss`, `.sass`, `.less`, `.module.css`, `.module.scss`
- Asset files: `.svg`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.ico`, `.webp`, `.woff`, `.woff2`, `.ttf`, `.eot`
- Theme/design config: files whose path contains `theme` and end in `.json` or `.ts`/`.js` (e.g., `theme.ts`, `themeConfig.json`)

A file is **logic-affecting** if it does NOT match the cosmetic-only patterns. This includes: `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.sh`, `.sql`, `.json` (non-theme), `.yaml`, `.yml`, `.toml`, `.md` (docs), config files, schema files, and anything else.

**c. Determine scope classification:**
- **Cosmetic-only:** ALL changed files match cosmetic-only patterns. No logic-affecting files exist.
- **Logic-affecting:** At least one changed file is logic-affecting.

**d. Log the classification** (REQUIRED — this feeds the validation report):
```
## Change-Scope Triage
- Changed files: {count} total
- Cosmetic files: {list of cosmetic files}
- Logic-affecting files: {list of logic files, or "none"}
- Classification: {COSMETIC_ONLY | LOGIC_AFFECTING}
- Decision: {SKIP baseline capture | PROCEED with full baseline capture}
```
Include this section in the **Regression Analysis** part of your validation report.

**e. If classification is COSMETIC_ONLY:** Skip the full baseline capture procedure (Steps 1-4 below). Instead:
1. Verify the branch builds successfully (run the project's build command once on the branch).
2. Run any AC-specific functional tests (e.g., if an AC says "auth flow still works," run the targeted auth test, not the full suite comparison).
3. Record the regression AC verdict as **PASS** with the note: "Cosmetic-only changes — baseline capture skipped per change-scope triage. Build succeeds and targeted functional checks pass."
4. Continue to step 5b (worktree cleanliness).

**f. If classification is LOGIC_AFFECTING:** Proceed with the full baseline capture procedure below (Steps 1-4).

---

**Portability constraint:** Baseline capture commands MUST work on stock macOS. Do NOT use `timeout`, `gtimeout`, `readlink -f`, `seq`, `tac`, or other GNU coreutils-only commands. For time-limited command execution, use the portable timeout surface named in your dispatch packet; if no sanctioned timeout surface is named, report the recipe gap instead of inventing an internal module command. The portable helper exits with code 124 on timeout, matching the GNU `timeout` convention.

**Baseline capture failure detection:** If the baseline capture step fails for any reason (command not found, nonzero exit from the wrapper, empty output when tests exist), you MUST report this as a **baseline capture failure** in the Regression Analysis section of your validation report. The verdict for any regression-related AC should be **INCONCLUSIVE** with an explanation, never PASS. An empty baseline set does NOT mean "no pre-existing failures" — it means the capture failed and you cannot reliably distinguish regressions from pre-existing issues.

## Step 1: Capture baseline failures on main and validate baseline trust

If a baseline failure list was provided in your dispatch prompt (as a file path), read it. Otherwise, capture it yourself using a **worktree-safe** approach — never `git checkout main` inside a worktree.

**Capture-path discipline:** the inline recipe below uses `mktemp /tmp/yoke-test.XXXXXX` because baseline capture wraps the project's `{test_command}` (any shell suite, not just pytest) and feeds it through the portable timeout helper. When the test_command IS a pytest run that may exceed ~60s, prefer the watcher wrapper instead — `python3 -m yoke_core.tools.watch_pytest -- <pytest args>` mints raw + filtered captures via `yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair("pytest")` under the machine temp root's watcher-captures directory and prints the resolved paths; inspect what the wrapper printed with `tail -80 <raw-capture>`. Operator carve-out: `--raw-capture <path>` pins the capture file to a known location (CI / artifact collection); the helper-resolved default is preferred. Do NOT hand-construct an OS-temp literal for the watcher capture — read the path the wrapper printed.

```bash
# Find the main worktree path (worktree-safe — no branch switching)
_main_wt=$(git worktree list --porcelain | awk '/^worktree /{p=$2} /^branch refs\/heads\/main$/{print p}')
_main_wt_exit=0
if [ -z "$_main_wt" ]; then
  # Fallback: if no dedicated main worktree is listed, derive the repo toplevel
  _main_wt=$(git -C {worktree_path} rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||')
  _main_wt_exit=$?
fi
_main_wt_branch=""
if [ -n "$_main_wt" ]; then
  _main_wt_branch=$(git -C "$_main_wt" branch --show-current 2>/dev/null || true)
fi
if [ "$_main_wt_branch" != "main" ]; then
  _main_wt=""
fi
# Run tests on main from the main worktree directory.
# IMPORTANT: use the sanctioned portable timeout surface, NOT GNU timeout.
_baseline_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
{portable_timeout} 120 sh -c "cd '$_main_wt' && sh {test_command}" >"$_baseline_tmp" 2>&1
_baseline_exit=$?
tail -50 "$_baseline_tmp"
# Parse failures, error messages, and locations from "$_baseline_tmp"
# If `_baseline_exit` is 124, the test timed out — note in report but proceed
# If `_baseline_exit` is 127 or "$_baseline_tmp" shows "command not found", baseline capture FAILED
rm -f "$_baseline_tmp"
```

Record the set of **failing test names** on main as `BASELINE_FAILURES`. If the baseline capture command itself failed (exit 127, "command not found", or produced no parseable test output), set `BASELINE_CAPTURE_FAILED=true` and proceed to Step 4 with an INCONCLUSIVE verdict for regression ACs. For each failure, also record:
- The **error/assertion message** (first line of the assertion or error output)
- The **failure location** (file:line or stack frame if available)

**Baseline trust validation.** After baseline capture, assess whether the baseline is **trusted** or **untrusted**. The baseline is **UNTRUSTED** if ANY of these conditions hold:
- (a) The baseline capture command itself exited non-zero due to a harness/tooling error (not a test failure — distinguish "tests ran and some failed" from "the test runner could not execute")
- (b) A required tool was missing or errored during capture (e.g., `timeout` not installed on macOS, `node` not found, test runner binary missing)
- (c) The baseline output is empty or unparseable (zero test results when tests were expected)
- (d) The main worktree could not be located via `git worktree list`, the fallback repo toplevel lookup failed, the resolved checkout was not actually on branch `main`, or the test execution in the main worktree failed due to a path or environment error

Record the baseline trust level as `BASELINE_TRUST`: `TRUSTED` or `UNTRUSTED`. If untrusted, record the reason as `BASELINE_UNTRUST_REASON`.

**When the baseline is UNTRUSTED:** No branch failures may be classified as "pre-existing." Skip Steps 3-4 below. Instead, report all branch failures as **indeterminate** (cannot confirm whether they are new or pre-existing). The verdict policy in Step 4 applies.

## Step 2: Capture branch failures

Run the same test suite on the branch (the worktree's current state) using the same capture-first temp-file pattern as Step 1 — generic `mktemp /tmp/yoke-test.XXXXXX` for shell-suite test commands, and `python3 -m yoke_core.tools.watch_pytest -- <pytest args>` (with helper-minted captures under the machine temp root's watcher-captures directory) for pytest runs that may exceed ~60s. Record the set of **failing test names** as `BRANCH_FAILURES`. For each failure, also record the error/assertion message and failure location (same signals as Step 1).

## Step 2a: Classify harness vs. product failures

Before comparing baseline and branch, separate **harness/tooling failures** from **product/test failures**. Harness failures include:
- Missing tools (command not found errors)
- Test runner crashes (segfault, OOM, uncaught runner exceptions)
- Environment setup failures (missing env vars, broken fixtures, permission errors)
- Comparison command errors (diff/sort/comm failures during the analysis itself)
- Broken baseline capture (the baseline step itself failed)

Record harness failures in a separate list: `HARNESS_FAILURES`. These block a PASS verdict regardless of product test results.

## Step 3: Compare sets with signature matching

For each test name that appears in BOTH `BASELINE_FAILURES` and `BRANCH_FAILURES`, perform **signature matching** — compare at least two of:
1. Test name (already matched by being in both sets)
2. Error/assertion message (first assertion failure line or error text)
3. Failure location (file:line or stack frame)

Classify each shared-name failure:
- **Pre-existing (signature match):** Test name matches AND at least one additional signal (error message or location) also matches. This failure is genuinely the same on both branches.
- **Indeterminate (name-only match):** Test name matches but NEITHER the error message NOR the failure location matches. The same test fails on both branches but for potentially different reasons. This CANNOT be classified as pre-existing.

Compute:
- **New regressions** = tests in `BRANCH_FAILURES` that are NOT in `BASELINE_FAILURES` (pass on main, fail on branch)
- **Fixes** = tests in `BASELINE_FAILURES` that are NOT in `BRANCH_FAILURES` (fail on main, pass on branch)
- **Pre-existing failures (signature match)** = tests in BOTH sets where signature matching confirms the same failure
- **Indeterminate failures** = tests in BOTH sets where only the name matches (different error signature)

## Step 4: Verdict with trust-level assessment

Determine verdict confidence:
- **HIGH:** Baseline is trusted AND green (zero baseline failures). All branch failures are definitively new.
- **MEDIUM:** Baseline is trusted AND red, but all shared failures have signature matches. Pre-existing failures are reliably classified.
- **LOW:** Baseline is trusted AND red, but some shared failures are indeterminate (name-only match). Pre-existing classification is uncertain.
- **UNTRUSTED:** Baseline capture failed or was incomplete. No pre-existing classification is possible.

Verdict rules:
- If **new regressions** is non-empty: **FAIL**. Report each regression explicitly:
  ```
  REGRESSION: {test_name} (passes on main, fails on branch)
  ```
- If **indeterminate failures** is non-empty: **FAIL**. Report each:
  ```
  INDETERMINATE: {test_name} (fails on both branches but error signatures differ — cannot confirm pre-existing)
  ```
- If **harness failures** is non-empty: **FAIL**. Report each:
  ```
  HARNESS FAILURE: {description} (tooling/infrastructure failure — blocks PASS)
  ```
- If **baseline is UNTRUSTED** and **branch has any failures**: **FAIL**. State in the report:
  ```
  Baseline untrusted — cannot classify failures as pre-existing. Reason: {BASELINE_UNTRUST_REASON}
  ```
- If **regressions** is empty AND **indeterminate** is empty AND **harness failures** is empty AND (baseline is trusted OR branch has zero failures): pre-existing failures (with signature match) do NOT count against the regression AC. Note them as informational:
  ```
  Pre-existing failures (signature-matched, not regressions): {count} tests
  ```
- If **fixes** is non-empty, note them positively: `Fixed on branch: {test_names}`

## Step 4a: Targeted validation fallback

When the generic test suite has a red baseline (trusted or untrusted), every task must still have at least one targeted validation path for the changed behavior. If acceptance criteria can be verified via targeted tests that pass:
- If the baseline is **trusted** and the red tests are genuinely pre-existing (signature match from Step 3), PASS is allowed with a note about the red baseline.
- If the baseline is **untrusted**, PASS is prohibited even if targeted tests pass — the untrusted baseline means the full regression picture is unknown.

**Important:** This comparison is mandatory whenever the task has a "no regressions" or "all existing tests pass" acceptance criterion. A matching failure count (e.g., 61 failures on main and 61 on the branch) does NOT mean "no regressions" — the sets of failing tests may differ. Always compare by name AND signature.
