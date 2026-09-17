## Required submission receipt block

Read this before you submit. It is the exact receipt shape, every required
field, and what an incomplete receipt costs the reviewer.

## Required Submission Receipt Block

Your final epic progress note MUST include this exact delimiter pair. The parent conduct session reads this block from the progress-note body field (see your `epic_progress_notes` packet stanza), not from the Agent tool result text:

```text
---SUBMISSION-CHECKS-START---
test_plan: PASS | SKIP - <what you ran or why skipped>
files_touched: PASS | SKIP - <what you verified or why skipped>
edited_tests: PASS | SKIP - <which edited test files ran or why skipped>
clean_worktree: PASS - git -C {worktree-path} status --porcelain is empty
progress_notes: PASS | SKIP - <epic note evidence or why skipped>
file_budget: PASS | SKIP - <evidence that authored files are at or below 350 lines, or why skipped>
---SUBMISSION-CHECKS-END---
```

Rules:
- `clean_worktree` MUST be `PASS`. There is no skip form.
- `test_plan`, `files_touched`, and `edited_tests` may be `SKIP` only when the task spec genuinely lacks that section or you edited no test files.
- `progress_notes` is `PASS` for epic tasks whenever you made a commit during this attempt; `SKIP` only for non-epic work or attempts with no new commits. `file_budget` is `PASS` when you created or grew authored code AND every authored file is at or below the 350-line hard limit (`yoke_core.domain.file_line_check`); `SKIP` only when no authored code was created or grown. When dispatch declares File Budget enabled, read the parent item's `## File Budget` section before writing the first new file; when disabled, use the dispatched execution scope without requiring that section. Missing line, malformed line, `FAIL`, or `UNKNOWN` re-dispatches the same attempt.
- This block is parsed by conduct from the DB. Missing block, missing lines, or any `FAIL`/non-`PASS` `clean_worktree` result blocks the item from advancing to `validate`.

Do not paraphrase the field names. Use the exact keys above so the parent conduct session can verify them reliably. You may repeat the block in your final chat response, but the DB progress note is the authoritative receipt.

---
