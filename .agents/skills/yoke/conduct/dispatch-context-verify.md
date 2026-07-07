# Dispatch Context — Conduct Direct Verification

Extracted from `dispatch-context-gates.md`. Contains the conduct
direct verification fallback (5i-conduct-verify).

**Watcher capture paths.** When conduct's direct-verification fallback drives a Yoke watcher (`watch_pytest`, `watch_merge`, `watch_doctor`, etc.), the raw + progress captures land at the helper-resolved location minted by `yoke_core.domain.project_scratch_dir.mint_watcher_capture_pair(...)` under `<scratch_root>/watcher-captures/`. Read the resolved path the wrapper prints; do not construct an OS-temp watcher-capture literal. The `mktemp /tmp/yoke-test.XXXXXX` shape used below for one-shot bare-command capture is governed by the AGENTS.md `## Command Output — Hard Rule` floor (capture-first to a temp file) — it is distinct from watcher captures and stays on the OS-temp default. Operator carve-out for pinning a watcher capture is `--raw-capture <path>`.

---

## 5i-conduct-verify. Conduct Direct Verification Fallback

When all Tester retries are exhausted (both full-prompt and minimal-prompt), the conduct skill verifies directly as a last resort. This is an explicit, documented exception to the Thin Conduct Principle.

**When to use:** After `_tester_output_failures > MAX_TESTER_REPROMPTS` (i.e., the initial full-prompt attempt plus all minimal-prompt retries have returned no parseable verdict).

**Procedure:**

1. **Identify test commands.** Scan the task spec (`_spec`) for executable test commands:
 - Look for commands under headings containing "Test" or "Acceptance" (case-insensitive)
 - Look for lines starting with `sh ` or containing common test patterns (`test-*.sh`, `pytest`, `npm test`)
 - If no test commands found, fall back to: find changed test files via `git diff --name-only main...HEAD` in the worktree, filtering for files matching `test*` or `*test*` patterns, and execute them directly

2. **Capture baseline with trust validation:**

 Use a **worktree-safe** approach — never `git checkout main` inside a worktree:
 ```bash
 # Find the main worktree path (worktree-safe — no branch switching)
 _main_wt=$(git worktree list --porcelain | awk '/^worktree /{p=$2} /^branch refs\/heads\/main$/{print p}')
 _main_wt_exit=0
 if [ -z "$_main_wt" ]; then
 _main_wt=$(git -C {_worktree_path} rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's|/\.git$||')
 _main_wt_exit=$?
 fi
 _main_wt_branch=""
 if [ -n "$_main_wt" ]; then
 _main_wt_branch=$(git -C "$_main_wt" branch --show-current 2>/dev/null || true)
 fi
 if [ "$_main_wt_branch" != "main" ]; then
 _main_wt=""
 fi
 ```

 **Baseline trust validation.** The baseline is **UNTRUSTED** if any of these hold:
 - (a) The main worktree could not be located, the fallback repo toplevel lookup failed, or the resolved checkout was not actually on branch `main` (`_main_wt` empty or `_main_wt_exit` non-zero)
 - (b) A required tool was missing or errored during baseline test execution (e.g., `timeout` not installed, test runner binary not found)
 - (c) The baseline test output is empty or unparseable (zero results when tests were expected)
 - (d) The baseline capture command exited non-zero due to a harness error (not a test failure)

 Run each test command on `main` from the main worktree directory. For each failure, capture:
 - The **test name**
 - The **error/assertion message** (first assertion failure line)
 - The **failure location** (file:line if available)

 **Portability:** Do NOT use `timeout` (GNU coreutils, unavailable on macOS) or the old internal timeout helper. Use the same capture-first shell shape from the resolved main worktree:
 ```bash
 _baseline_tmp=$(mktemp /tmp/yoke-test.XXXXXX)
 sh -c "cd '$_main_wt' && sh {test_command}" >"$_baseline_tmp" 2>&1
 _baseline_exit=$?
 tail -50 "$_baseline_tmp"
 ```
 Parse failures from `$_baseline_tmp`, then remove it after analysis. If baseline capture fails (`_baseline_exit` 127, "command not found", empty output, or `_main_wt` was empty), set `BASELINE_TRUST=UNTRUSTED`.

 Record `BASELINE_TRUST` as `TRUSTED` or `UNTRUSTED` with reason.

3. **Execute tests on the branch with signature matching.**

 **Capture-first test output discipline:** Never pipe test output directly to `tail` or `head`. Always capture to a temp file first:
 ```bash
 _tmp=$(mktemp /tmp/yoke-test.XXXXXX)
 sh {test_command} >"$_tmp" 2>&1; _test_exit=$?
 tail -50 "$_tmp"
 ```
 Inspect `$_tmp` for failure details. Clean up after analysis.
 For each branch failure, capture the same three signals (test name, error message, location). If baseline capture failed, the regression verdict must be INCONCLUSIVE, not PASS.

 **Classify harness vs. product failures.** Separate harness/tooling failures (missing tools, runner crashes, env setup errors) from product/test failures. Harness failures block PASS.

 **Path-claim ownership is not a pre-existing-failure signal.** Future/planned item ownership or a planned path claim does not justify classifying current branch failures as pre-existing. If direct verification exposes a failure whose fix touches a file outside the active claim, widen the claim and encode dependency or claim reconciliation before retrying. Do not use `path-claim-override` for a planned future claim when dependency or claim reconciliation can resolve the ordering; override is last resort for irreducible live collisions and requires explicit operator approval.

 **Compare sets with signature matching.** For test names appearing in both `BASELINE_FAILURES` and `BRANCH_FAILURES`:
 - **Pre-existing (signature match):** Name matches AND at least one additional signal (error message or location) also matches.
 - **Indeterminate (name-only match):** Name matches but error signature differs. Cannot confirm pre-existing.

 Compute:
 - **New regressions** = in `BRANCH_FAILURES` but not `BASELINE_FAILURES`
 - **Pre-existing (signature match)** = in both, with matching error signature
 - **Indeterminate** = in both, with different error signature
 - **Harness failures** = tooling/infrastructure errors (separate category)

4. **Produce synthetic verdict:**
 - If `BASELINE_TRUST` is `UNTRUSTED` AND branch has any failures:
 - Log: `Conduct direct verification: YOK-{_id} FAIL (baseline untrusted — cannot classify failures as pre-existing)`
 - Classify item as FAILED
 - **PASS is prohibited when baseline is untrusted and failures exist.**
 - If harness failures exist:
 - Log: `Conduct direct verification: YOK-{_id} FAIL (harness/tooling failures present)`
 - Classify item as FAILED
 - If indeterminate failures exist (name-only match, different error signature):
 - Log: `Conduct direct verification: YOK-{_id} FAIL (indeterminate failures — cannot confirm pre-existing)`
 - Classify item as FAILED
 - If ALL test commands exit 0 AND no regressions AND no indeterminate AND no harness failures:
 - Log: `Conduct direct verification: YOK-{_id} PASS`
 - Classify item as PASSED
 - Create Ouroboros entry:
 ```bash
 yoke ouroboros entry insert \
 --agent conduct --category problem --context "YOK-${_id}" \
 --observation "Conduct had to verify YOK-${_id} directly after all Tester retries returned empty output. Tests passed. This indicates context saturation in the Tester — investigate diff size."
 ```
 - If new regressions exist (pass on main, fail on branch):
 - Log: `Conduct direct verification: YOK-{_id} FAIL`
 - Classify item as FAILED
 - Store test output as `_tester_feedback_{_id}` for retry context
 - If baseline is trusted AND red, but all shared failures have signature matches AND no new regressions:
 - PASS is allowed. Pre-existing failures (signature-matched) do not count against the verdict.
 - Log: `Conduct direct verification: YOK-{_id} PASS (pre-existing failures signature-matched, no regressions)`

5. **Log the transition:**
 ```
 Tester output gate exhausted: conduct verifying YOK-{_id} directly
 Baseline trust: {TRUSTED|UNTRUSTED} {reason if untrusted}
 Conduct direct verification: YOK-{_id} {PASS|FAIL}
 ```

 **Green baseline fast path.** When the baseline is trusted and green (zero failures on main), the procedure above simplifies: all branch failures are definitively new regressions, no signature matching needed, no trust gates to evaluate.
