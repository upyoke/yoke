# Merge — Preflight

Covers merge Steps 1 through 5: require integration simulation, verify epic-level acceptance criteria against worktree paths, verify all tasks are complete, read the worktree plan, and determine merge order.

**Context variables** (consumed by later phases): `{epic-id}`, `_epic_ref`,
`_epic_id`, `_worktrees`, `WORKTREE_PATH`, `_worktree_plan`.

---

## Steps

1. **Require integration simulation:**
 Check if a canonical integration simulation report exists in the DB:
 ```bash
 _sim_record=$(yoke workflow-item epic-task simulation-get --epic "$_epic_id" --phase integration 2>/dev/null) && _sim_rc=0 || _sim_rc=$?
 ```
 If `_sim_rc` is non-zero or `_sim_record` is empty, print the following error and **STOP** (do not proceed to subsequent steps):
 > **Error: Integration simulation required before merge.**
 >
 > No canonical integration simulation report found for epic `{epic-id}`.
 > Run `/yoke simulate {epic-id}` to check for integration gaps across worktrees before merging.
 >
 > To bypass this check, re-run with `--skip-simulation`:
 > `/yoke merge {epic-id} --skip-simulation`

 **`--skip-simulation` override:** If the user passes `--skip-simulation`, skip the simulation check entirely and proceed to Step 2 regardless of whether a canonical simulation report exists. This is intended for cases where the user has already verified integration manually or the epic has a single worktree with no cross-branch risk.

 If `_sim_rc` is 0 and `_sim_record` is non-empty, proceed silently to Step 2.

2. **Verify epic-level acceptance criteria:**
 Read the rendered body for the epic backlog item via
 `yoke items get "$_epic_ref" body` (the body is a virtual rendered field —
 never selected via raw SQL on `items`). Find the `### Acceptance Criteria`
 section (under `## Technical Plan`). Count the total ACs first, then for each
 AC listed:

 **CRITICAL — Scope all checks to worktree paths, not main.** Before verifying
 ACs, read the epic task rows through the registered reader:
 ```bash
 yoke epic-tasks list --epic "$_epic_id"
 ```
 Retain the distinct non-empty lane branches from the fourth pipe-delimited
 field as `_worktrees`. For each branch, resolve its local path:
 `WORKTREE_PATH=".worktrees/$(echo {branch} | tr '/' '-')"`. All file reads,
 greps, and existence checks **MUST** target these worktree paths (e.g.,
 `grep ... "$WORKTREE_PATH/..."`, `[ -f "$WORKTREE_PATH/..." ]`). **Never
 check files in the main working directory** — before merge, the feature code
 only exists in worktrees. If dispatching sub-agents for parallel AC
 verification, pass the explicit worktree path(s) in the agent prompt and
 instruct them to scope all file operations there.

 **Print progress before each check** so the user knows the merge isn't hung:
 ```
 Verifying AC {i}/{total}: {AC text (first 80 chars)}...
 ```

 - Check whether the condition is demonstrably satisfied **in the worktree files** (grep for expected strings, verify files exist, check that referenced features are present — all within the `WORKTREE_PATH`).

 **Print the result after each check:**
 ```
 AC-{i}: PASS
 ```
 or
 ```
 AC-{i}: FAIL — {specific reason}
 ```

 - If an AC cannot be verified, report it and abort. The user must either fix the gap (via `/yoke amend` or direct work) or acknowledge it before proceeding.

 **Print a summary after all ACs:**
 ```
 AC verification: {pass_count}/{total} passed
 ```

 If the backlog item body has no `### Acceptance Criteria` section (under `## Technical Plan`), warn:
 > **Warning:** No epic-level acceptance criteria found in the backlog item body. Epic requirements may not be fully verified. Consider adding an `### Acceptance Criteria` section under `## Technical Plan`.

 Proceed after the warning — this maintains backward compatibility with older epics.

3. **Verify all tasks are complete:**
 Inspect the registered epic-task rows read in step 2. The third
 pipe-delimited field is the task status. If any row is outside
 `reviewed-implementation`, `polishing-implementation`, `implemented`,
 `release`, or `done`, report which tasks are still pre-dispatch, in progress,
 or failed and abort.

4. **Read the worktree plan:**
 Read the `worktree_plan` field through the registered item reader:
 ```bash
 yoke items get "$_epic_ref" worktree_plan
 ```
 Retain the printed content as `_worktree_plan` and parse it for the branch
 merge order. If the field is empty, reuse the lane branches from the
 registered epic-task rows read in step 2.

5. **Determine merge order:**
 The worktree plan specifies execution order. Merge in the same order — branches that were independent can merge in any order, but if there's a suggested sequence, follow it.
