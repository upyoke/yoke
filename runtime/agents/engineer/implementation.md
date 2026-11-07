# Engineering implementation and submission

Read after confirming the lane, before editing, and again before submission.

## Process

1. Read the whole task: description, acceptance criteria, test plan,
   interfaces, docs and files touched. Confirm each dependency interface exists
   with the exact signature and behavior the task assumes; a mismatch is a
   blocker you report, not a gap you guess around.
2. Implement the assigned scope. Find every consumer of a renamed or removed
   name with a scoped `rg` and leave no residue.
3. Write and run the specified tests and update every doc the change makes
   wrong. Run a failing test alone to diagnose it.
4. Commit each coherent unit, then run `git -C {worktree-path} status
   --porcelain` and commit the generated, test or config files it shows before
   the next unit. Nothing commits for you.
5. Verify every acceptance criterion and the pre-submit checks below.

Tests that create items, issues or other durable records use test-database
fixtures, never the live backlog, counters or GitHub. Filesystem fixtures live
under `/tmp` or designated scratch and clean up on success and failure.

## Pre-submit checks

Each maps to a receipt key in your agent prompt.

1. `test_plan`: cite the commands that passed after the last relevant change.
2. `files_touched`: recheck every file the task names; implement an omission
   or say why it is intentionally untouched.
3. `edited_tests`: after the final change, run every test file you edited.
4. `clean_worktree`: commit every related file, write the progress note, then
   confirm `git -C {worktree-path} status --porcelain` is empty.

## Progress notes

After each epic commit, append a progress note; the final one carries the
submission receipt:

```bash
yoke workflow-item epic-progress-note append --epic {epic-ref} \
  --task-num {task-num} --note-num {note-num} --body-file <absolute-note-file>
```

A note records the commit, a short summary, changed files and, while work is
unfinished, the next action and any blocker.

## Operator decisions

A subagent receives no Fleet mail, so it cannot wait for an operator's answer.
Finish the in-scope work the question does not block, then return the question
to the parent with its context, options and your recommendation.
