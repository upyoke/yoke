# Merge — Preflight

Covers merge Steps 1 through 5: require integration simulation, verify epic-level acceptance criteria against worktree paths, verify all tasks are complete, read the worktree plan, and determine merge order.

**Context variables** (consumed by later phases): `{epic-id}`, `_worktrees`, `WORKTREE_PATH`, `_item_id`, `_worktree_plan`.

---

## Steps

1. **Require integration simulation:**
 Check if a canonical integration simulation report exists in the DB:
 ```bash
 _sim_record=$(python3 -m yoke_core.cli.db_router epic simulation-get "{epic-id}" "integration" 2>/dev/null) && _sim_rc=0 || _sim_rc=$?
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
 Read the rendered body for the epic backlog item via `yoke items get YOK-{epic-id} body` (the body is a virtual rendered field — never selected via raw SQL on `items`). Find the `### Acceptance Criteria` section (under `## Technical Plan`). Count the total ACs first, then for each AC listed:

 **CRITICAL — Scope all checks to worktree paths, not main.** Before verifying ACs, collect the worktree paths for this epic:
 ```bash
 _worktrees=$(python3 -m yoke_core.cli.db_router query "SELECT DISTINCT worktree FROM epic_tasks WHERE epic_id={epic-id} AND worktree IS NOT NULL ORDER BY task_num")
 ```
 For each worktree branch, resolve its local path: `WORKTREE_PATH=".worktrees/$(echo {branch} | tr '/' '-')"`. All file reads, greps, and existence checks **MUST** target these worktree paths (e.g., `grep ... "$WORKTREE_PATH/..."`, `[ -f "$WORKTREE_PATH/..." ]`). **Never check files in the main working directory** — before merge, the feature code only exists in worktrees. If dispatching sub-agents for parallel AC verification, pass the explicit worktree path(s) in the agent prompt and instruct them to scope all file operations there.

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
 Query `epic_tasks` in the DB for any non-terminal tasks:
 ```bash
 _incomplete=$(python3 -m yoke_core.cli.db_router query "SELECT task_num, title, status FROM epic_tasks WHERE epic_id={epic-id}' AND status NOT IN ('reviewed-implementation','polishing-implementation','implemented','release','done') ORDER BY task_num")
 ```
 If any rows are returned, report which tasks are still pre-dispatch, in progress, or failed and abort. Every task must be in terminal success (`reviewed-implementation`, `polishing-implementation`, `implemented`, `release`, or `done`) before merging.

4. **Read the worktree plan:**
 Read the `worktree_plan` field directly from the DB. `{epic-id}` IS the epic item's numeric `items.id`, so resolve to the item row by `id`:
 ```bash
 _item_id=$(python3 -m yoke_core.cli.db_router query "SELECT id FROM items WHERE id={epic-id} AND type='epic' LIMIT 1")
 _worktree_plan=$(yoke items get $_item_id worktree_plan)
 ```
 Parse the worktree plan content to get the list of branches and their merge order. If the `worktree_plan` field is empty, derive the branch list from `epic_tasks`:
 ```bash
 python3 -m yoke_core.cli.db_router query "SELECT DISTINCT worktree FROM epic_tasks WHERE epic_id={epic-id}' AND worktree IS NOT NULL ORDER BY task_num"
 ```

5. **Determine merge order:**
 The worktree plan specifies execution order. Merge in the same order — branches that were independent can merge in any order, but if there's a suggested sequence, follow it.
