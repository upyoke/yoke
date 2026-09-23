## Selecting and running tests

Read this before step 5 of your process. It is the full selection
procedure, the execution shapes, and how a failure is attributed.

5. **Select and run tests.** Use your judgement to decide which tests to run based on your understanding of the change's scope and risk. All selected tests must pass. Do not default to running every test file — think about what could actually break.

   Guidelines for test selection:
   - **Always run** tests whose names match changed files or changed command surfaces (e.g., changing a project-provided command means running that command's matching test) and any tests listed in the task's acceptance criteria.
   - **Consider running** tests for scripts that source or depend on the changed code. `grep -rl` on changed filenames in the test directory can help identify these.
   - **Escalate to broader runs** when your judgement says the blast radius warrants it — e.g., changes to core infrastructure, shared helpers, DB schema, or wide-reaching refactors. For Yoke code, prefer `yoke watch pytest --impacted main --bounded` (`--bounded` reports an unbounded selection instead of widening to the full sweep, because the item's QA case run is the one full execution for that tree). For a project declaring `ci_workflow_file` it executes on that project's CI by default against the pushed lane commit, so it costs this machine nothing and refuses an uncommitted tree. `--local` is only a small targeted check expected to finish in about one minute; uncommitted work does not justify a slow local run. The full three-anchor sweep is CI's job on the protected merge path and returns locally only as the CI-outage fallback. A single leaf script getting a new feature almost certainly doesn't need 90+ test files.

   Log your test selection reasoning in the validation report: what you chose to run, why, and what you considered but excluded.

   **Capture-first test output discipline.** Never pipe a live test-suite invocation directly to `tail` or `head` — this silently discards failure context. Always capture test output to a temp file first, then inspect:
   ```bash
   _tmp=$(mktemp /tmp/yoke-test.XXXXXX)
   sh {test-command} >"$_tmp" 2>&1; _rc=$?
   tail -50 "$_tmp"                          # inspect captured output
   grep -E "FAIL|ERROR|error" "$_tmp" || true # extract failures
   rm -f "$_tmp"
   exit "$_rc"
   ```
   Post-capture `tail`/`head` usage on the temp file is fine.

   **For long runs, use the watcher wrapper.** When the expected runtime exceeds ~60s, run `yoke watch pytest -- <pytest args>` (or `yoke watch merge done-transition <args>` / `yoke watch merge merge-worktree <args>` for merges) using the wait shape its harness selects. Pytest streams filtered progress; merge streams actionable errors and the final result only. Every wrapper writes a raw capture for post-completion inspection.
<!-- YOKE:HARNESS claude start -->

   **Subagent dispatched turns are foreground-only — never arm a background `Bash` task paired with `Monitor` and end the turn.** Dispatched subagent turns are atomic: a `Monitor` wake fired after this turn ends has nowhere to deliver, so the subagent suspends with an `agentId: <id> (use SendMessage with to: '<id>' to continue this agent)` envelope and the parent dispatch deadlocks. The watcher wrapper above runs foreground inside a single `Bash` tool call and exits before the turn does — that is the canonical long-command shape for subagents. After completion, inspect the helper-resolved raw capture (the path `--print-streaming-pair` emits, minted by `yoke_core.domain.project_scratch_dir.watcher_capture_path(...)` under the machine temp root's watcher-captures directory) with `tail -80`. If you passed `--raw-capture <path>` to pin the capture file to a known location (CI / artifact collection), inspect that path instead. If the turn budget cannot accommodate the foreground run, surface a tighter dispatch scope to the parent session — do not arm background work and return. See `session.md` `## Tool Constraints` for the full rule.

   Example (preferred — foreground watcher wrapper writes raw + filtered progress captures to the helper-resolved scratch root):
   ```bash
   # No --raw-capture: the wrapper mints both raw + progress captures via
   # project_scratch_dir.mint_watcher_capture_pair("pytest") and prints
   # the resolved paths. Inspect those after exit.
   yoke watch pytest --impacted main --bounded
   # --impacted needs no project paths. Full-sweep anchor paths are per-project:
   # read them from the project's registered verification command (or project
   # rules file) rather than hardcoding another project's layout.
   # Operator carve-out: pass --raw-capture <PATH> to pin to a known path
   # (CI / artifact collection). The helper-resolved default is preferred.
   ```
<!-- YOKE:HARNESS end -->

5a. **Baseline-validated regression detection.** When the task acceptance criteria include "no regressions" or "existing tests still pass," do NOT simply compare failure counts between main and the branch — they can match by coincidence when a pre-existing failure is fixed while a new regression is introduced.

   **Read and follow the embedded Baseline-Validated Regression Detection reference** for the full procedure: change-scope triage (cosmetic-only vs. logic-affecting), portable baseline capture against the worktree-safe main checkout, baseline trust validation, branch capture, harness-vs-product failure classification, signature matching for shared-name failures, the trust-level verdict assessment, and the targeted-validation fallback when the baseline is red. The verdict rules in that reference feed back into your validation report's Regression Analysis section.

5b. **Check worktree cleanliness.** After tests complete, verify the worktree has no unexpected artifacts left behind by the Engineer's test scripts. Run `git status --porcelain` in the worktree and compare against the task's "Files touched" list. Any unexpected untracked files or directories (especially nested directory trees from captured command output) should be flagged as a test artifact leak — this is a **FAIL** condition.
