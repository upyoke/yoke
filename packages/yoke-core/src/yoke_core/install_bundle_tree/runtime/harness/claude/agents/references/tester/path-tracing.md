## Path tracing beyond the task

Read this before step 4 of your process. It is the full procedure for
tracing the paths a change participates in, with the worked cases that
decide close calls.

4. **Path tracing (beyond this task).** After verifying interface contracts against the spec, trace the key paths this code will participate in:

   - **Export verification:** Do the *actual* exports match the interface contract exactly? Not just "does the function exist" but: is the export named or default? Are the argument types exact? Does the return type match? Are optional fields actually optional?
   - **Runtime assumptions:** Are there assumptions about the runtime environment that aren't guaranteed? File/directory existence, environment variable dependencies, external service availability, path assumptions (absolute vs relative, CWD expectations).
   - **Downstream compatibility:** When downstream tasks consume this code, will the *actual* implementation match what they expect? Read the "Expects" contracts of dependent tasks (file paths provided in the dispatch prompt) and verify the implementation matches their expectations, not just this task's "Provides" spec.

   Flag path-tracing concerns in a separate section of the validation report. A task can **PASS** tests but still have integration **warnings** that should be noted for the operator.

4a. **Prose-only detection heuristic.** Before running the test suite, check whether the diff contains ONLY non-executable file types. If so, the full test suite is structurally unnecessary — markdown changes cannot cause shell script test regressions.

   **Procedure:**
   1. Compute the list of changed files from the diff:
      ```bash
      # For standalone issues or full-branch diffs:
      git diff main...HEAD --name-only
      # For epic per-task diffs (if TASK_BASELINE is provided):
      git diff {TASK_BASELINE}..HEAD --name-only
      ```
   2. Extract the file extensions and check against the **prose-only allowlist**: `.md`
   3. If ALL changed files have extensions on the allowlist (or the diff is empty):
      - **Skip the full test suite** (steps 5, 5a, 5b).
      - Log in your validation report: "Prose-only change detected ({N} .md files). Skipping test suite — regressions structurally impossible."
      - In the Regression Analysis section, write: "Skipped — prose-only change, no executable files modified."
      - **Still run acceptance criteria verification** (steps 1-4 and 6-7 proceed normally).
   4. If ANY changed file has an extension NOT on the allowlist (e.g., `.sh`, `.py`, `.json`, `.yaml`, or no extension): proceed to step 5 for risk-scoped test selection. Files with no extension are treated as executable (not on the allowlist).

   **Important:** The allowlist starts with `.md` only — do not expand it without evidence.

4b. **Project test command selection.** If your dispatch prompt includes a `Project Test Commands` block, use those commands instead of file-based test discovery. Project-provided commands take precedence because they encode project-specific knowledge about how to run tests (build steps, environment setup, test runners, etc.).

   **Procedure:**
   1. Check whether the dispatch prompt contains a `Project Test Commands` block with `Quick`, `Full`, and/or `E2E` entries.
   2. If present and non-empty, use the project commands as your primary test execution method:
      - **Quick:** Use for fast smoke tests during initial validation. Suitable for step 5 test selection when the change scope is narrow.
      - **Full:** Use for comprehensive test runs. Suitable for step 5 when the blast radius is wide or when "no regressions" is an acceptance criterion.
      - **E2E:** Defers to step 4c (ephemeral E2E validation). Do not run E2E commands directly in step 5.
   3. If the `Project Test Commands` block is absent or all entries are empty, fall back to file-based test discovery in step 5.
   4. Log which command source you used (project commands vs. file-based discovery) in the "Test Commands Used" section of your validation report.

   **Important:** Project commands and file-based discovery are mutually exclusive for a given test run. When project commands are available, do not also run file-based discovered tests unless the project commands are insufficient to cover the changed code.

4c. **E2E execution against ephemeral URL.** This step runs AFTER unit and integration tests pass (steps 4b/5). If unit or integration tests failed, skip E2E entirely — the verdict is already FAIL.

   **Prerequisites — graceful skip when not applicable:**
   - If the dispatch prompt does not include an `Ephemeral URL` line, or the value is `"none"` or empty: skip this step. Log: "E2E skipped — no ephemeral URL provided."
   - If the `Project Test Commands` block has no `E2E` entry, or the E2E command is empty: skip this step. Log: "E2E skipped — no E2E test command configured."
   - Both conditions must be satisfied to proceed. If either is missing, skip gracefully.

   **Procedure:**
   1. Extract the ephemeral URL from the dispatch prompt (`Ephemeral URL: {url}`).
   2. Extract the E2E command from the `Project Test Commands` block (`E2E: {command}`).
   3. Run the E2E command with `BASE_URL` injected:
      ```bash
      BASE_URL={ephemeral_url} {e2e_command}
      ```
   4. If the command exits with a non-zero status, E2E tests have failed.

   **Failure reporting:** When E2E tests fail, collect and report:
   - **Test names:** Each failing test's name or description (parsed from the test runner output).
   - **Error messages:** The assertion or error message for each failure.
   - **Artifact paths:** Paths to Playwright artifacts — screenshots (`*.png`), traces (`*.zip`), and videos if present. These are typically found in a `test-results/` or `playwright-report/` directory relative to the project root. List each artifact path so the operator can inspect them.

   **Verdict impact:** If E2E tests fail, the overall verdict is **FAIL** — even if all unit and integration tests passed. E2E failures indicate the deployed application does not behave correctly, which is a blocking issue.
