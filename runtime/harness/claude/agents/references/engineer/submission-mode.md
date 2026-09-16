## Submission mode protocol

Read this once you know which submission mode your dispatch selected. It is
the full protocol per mode and what each one expects you to hand back.

## Submission Mode Protocol

When you enter submission mode (30 or fewer turns remaining), you MUST follow this constrained protocol. Submission mode is **finish-the-current-branch-state only** — not a time to start new work.

**Allowed in submission mode:**
1. Commit any in-progress coherent work (even if partial)
2. Run only still-missing required verification (do NOT re-run tests that already passed)
3. Write the required progress note (for epic tasks with new commits)
4. Confirm a clean worktree (`git -C {worktree-path} status --porcelain`)
5. Write the required `---SUBMISSION-CHECKS-START---` block into the final epic progress note
6. Produce the `---REFLECTION-START---` block and stop

**Forbidden in submission mode:**
- Starting new implementation work, new files, or new features
- Broad exploratory searches or codebase investigation
- Optional cleanup, refactoring, or code improvement
- Re-running verification that already passed earlier in the session

**Evidence-based submission checks:** When entering submission mode, you do NOT need to ceremonially re-read and re-run everything from scratch. Instead:
- **Check 1 (test_plan):** If you already ran the test plan commands earlier and they passed, cite that evidence (e.g., "PASS - ran at turn ~50, all 12 tests passed"). Only re-run if you made changes after the last passing run.
- **Check 2 (files_touched):** If you already verified files touched during implementation, cite that evidence. Only re-verify files you changed after the last check.
- **Check 3 (edited_tests):** Mandatory final-pass check — you MUST run every test file you edited, even if you ran them before. Test files may have been affected by later changes.
- **Check 4 (clean_worktree):** Mandatory final-pass check — you MUST run `git -C {worktree-path} status --porcelain` and commit anything remaining. No exceptions.
