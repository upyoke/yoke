# Worktree Lifecycle

Yoke isolates all work in Git worktrees. Every backlog item that reaches `implementing` status gets its own branch and worktree directory. This document describes the four phases of the worktree lifecycle.

## Phase 1: Create

**Owning script:** `create-worktree.sh` (unified, project-aware)
**Triggered by:** `/yoke advance YOK-N implementing` (via `advance/SKILL.md`)

When a backlog item is advanced to `implementing`, Yoke creates an isolated worktree:

1. `create-worktree.sh` creates branch `YOK-{N}` and worktree at `.worktrees/YOK-{N}`.
2. `advance/SKILL.md` stores the branch name (`YOK-{N}`) in the backlog item's `worktree` DB field.
3. The absolute worktree path is printed to the agent so all subsequent operations use absolute paths.

### External project items
When an item's `project` column references a non-yoke project, worktrees are created in the target project's repository:

1. The conduct queries `items.project` to determine the target project.
2. `create-worktree.sh` accepts a `--project <project-id>` flag that resolves `repo_path` and `default_branch` from the `projects` table via `project-db.sh`.
3. The worktree is created at `{repo_path}/.worktrees/YOK-{N}` in the target project's repository.
4. The base branch defaults to the project's `default_branch` (from the `projects` table), falling back to `main` if unset.

**Example:** A Buzz item `YOK-42` with `project='buzz'` creates a worktree at `/Users/dev/buzz/.worktrees/YOK-42`.

All worktrees now use the canonical `YOK-{N}` naming for both branches and directories.

The create step is idempotent: if the worktree already exists, the script returns the existing path.

## Phase 2: Work

**Agent context:** Engineer operates inside the worktree with absolute paths.

During this phase:

- All file reads, writes, edits, and commands use absolute paths rooted at the worktree directory (e.g., `/path/to/repo/.worktrees/YOK-{N}/`).
- The agent commits incrementally to the worktree's branch.
- Shared files (`data/BOARD.md`) are on the base branch and updated via the base repo, not the worktree.
- The worktree branch is independent of other worktrees and the main branch.

## Pre-Merge: Deployment Flow Guard

**Owning script:** `done-transition.sh` (Step 2a, YOK-576)
**Triggered by:** `/yoke usher YOK-N` (via `done-transition.sh`)

Before the merge guard, `done-transition.sh` checks whether the item has a deployment flow. If `deployment_flow` is set (non-null, non-empty) and `deploy_stage` is not `complete`, the transition is refused with exit code 6. This prevents callers from bypassing the deployment pipeline managed by the Usher skill.

- **No deployment flow:** Guard is skipped entirely (item is Yoke-internal). Zero behavior change.
- **Deployment flow with `deploy_stage = 'complete'`:** Guard passes. The Usher has completed the pipeline.
- **Deployment flow with `deploy_stage` not `complete`:** Transition refused (exit code 6). Error message includes item ID, flow name, current deploy_stage, and directive to use `/yoke usher`.

The guard gracefully degrades when the `deployment_flow`/`deploy_stage` columns do not exist (pre-YOK-563) -- missing columns return empty values, so the guard is effectively a no-op.

## Pre-Merge: Merge Guard

**Owning script:** `done-transition.sh` (Step 2b)
**Triggered by:** `/yoke usher YOK-N` (via `done-transition.sh`)

Before the merge phase begins, `done-transition.sh` runs a merge guard check. If the item has a `worktree` field set, the guard verifies the branch has been merged to main using `git merge-base --is-ancestor`:

- **Branch exists and is merged:** Transition proceeds.
- **Branch exists and is NOT merged:** Transition is refused with exit code 1. The operator must merge the branch first or remove the worktree field if no worktree was actually used.
- **Branch does not exist locally:** Treated as already merged and cleaned up (normal for branches deleted after merge). Transition proceeds.
- **No worktree field:** Guard is bypassed (item was worked on main).

This prevents premature done-transitions when worktree code has not landed on main.

### done-transition.sh exit codes

| Code | Meaning | Recovery |
|------|---------|----------|
| 0 | Success (or idempotent re-run) | -- |
| 1 | Merge failure | Resolve issue, re-run `/yoke usher YOK-N` |
| 2 | CWD enforcement or argument error | Fix CWD or arguments |
| 3 | Blocked before done: integration simulation gate failure (epic items) or merge conflicts requiring agent resolution | Run `/yoke simulate` first, or resolve the merge conflicts and retry |
| 4 | User files at risk (passthrough from merge-worktree.sh) | Commit or move the files, then retry |
| 6 | Deployment flow guard (YOK-576) | Complete the deployment pipeline via `/yoke usher` |

## Phase 3: Merge

**Owning script:** `merge-worktree.sh`
**Triggered by:** `/yoke usher YOK-N` (via `done-transition.sh`)

The merge phase is the most complex. `merge-worktree.sh` performs a full automated merge:

0. **DB lock** — Acquires a merge lock via `merge-lock.sh` (`merge_lock_check` + `merge_lock_acquire`). Prevents concurrent merge operations from colliding when multiple Conduct sessions run in parallel. The lock is held for the duration of the merge and released on completion or failure. If another session holds the lock, the merge exits with a diagnostic message. Smart stale detection auto-cleans locks from crashed sessions (dead PID). Emergency override: `--force-lock` clears all locks before proceeding. Lock TTL is configurable via `merge_lock_ttl_minutes` in `yoke/config` (default: 30 minutes).
1. **Repo-root check** — Verifies it is running from the main repository root, not from inside a worktree.
1a. **Project-aware repo resolution (YOK-562)** — Parses the item ID from the branch name, queries `items.project`, and if the project is non-yoke, overrides `REPO_ROOT` with the project's `repo_path`. The original Yoke repo root is preserved as `YOKE_REPO_ROOT` for DB and lock access. The merge target branch is resolved from the project's `default_branch` unless explicitly specified. See [External Project Worktrees](#external-project-worktrees) for details.
2. **Safety stash** -- Creates `yoke-pre-rebase-YOK-{N}` stash (unconditional) to preserve all dirty state including untracked files.
3. **File classification** — Classifies every dirty file in the worktree as either:
   - **Yoke-managed** (`YOKE_SHARED_FILES`): files like `data/BOARD.md` that are shared across branches and can be safely discarded from the worktree.
   - **User-authored**: any file not in the shared list, which must be preserved.
4. **Safety gate** — If any user-authored files are dirty, exits with code 4 (HARD STOP). Lists the at-risk files and preserves the safety stash for recovery.
5. **Rebase** — Rebases the worktree branch onto the base branch. Auto-resolves conflicts in generated files (lock files, compiled output), doc files (`CLAUDE.md`, `yoke/README.md`, `yoke/docs/*`) that the branch did not modify, and provably additive code/test conflicts where both sides only added lines with no deletions from base (YOK-1205, resolved via `git merge-file --union`). Doc files intentionally modified by the branch (detected via `BRANCH_CHANGED_FILES`, computed before the rebase from the merge-base diff) are NOT auto-resolved — they trigger the merge-commit fallback or agent resolution diagnostic (YOK-538). Conflicts that are not provably additive exit with code 3 and structured per-file classification output for agent-assisted resolution.
6. **Test** — Runs the project test suite on the rebased code.
7. **Push** — Pushes the rebased branch to the remote.
8. **PR** — Creates a pull request via `gh pr create`.
9. **CI** — Waits for CI checks to pass.
10. **Merge** — Merges the PR via `gh pr merge`.
11. **Cleanup stash** — Drops the safety stash after successful merge. On failure, the stash is preserved for recovery.
12. **YOKE_REPO_ROOT sentinel** — Prints `YOKE_REPO_ROOT=/path/to/repo` as the last line of output so the calling SKILL can `cd` back to the repo root after the worktree is deleted.

### Exit codes

| Code | Meaning | Recovery |
|------|---------|----------|
| 0 | Success | Proceed to cleanup |
| 1 | Merge failure (test, push, CI) | Resolve issue, re-run `/yoke usher YOK-N` |
| 3 | Conflicts present, agent resolution possible (YOK-1205) | Agent inspects `CONFLICT\|file\|classification` lines on stderr and resolves |
| 4 | User files at risk (HARD STOP) | Commit or move the files, then retry |

## Phase 4: Cleanup

**Triggered by:** `merge-worktree.sh` (on success) and `done-transition.sh` (Step 4a)

After a successful merge:

1. **Worktree removal** — `git worktree remove` deletes the worktree directory.
2. **Branch deletion** — The worktree branch is deleted locally (and remotely if it was pushed).
3. **CWD verification** — `done-transition.sh` (called by usher) parses the `YOKE_REPO_ROOT` sentinel from merge output and `cd`s to that path. It verifies:
   - The path does not contain `.worktrees/` (would indicate a deleted worktree).
   - `pwd` matches the expected repo root.
4. **Worktree field cleanup** — The backlog item's `worktree` DB field is set to `null`.
5. **Stale worktree/branch cleanup (Step 4a)** — `done-transition.sh` performs a best-effort sweep for the `YOK-{N}` worktree directory and branch if they were not cleaned up by the merge pipeline.
   - Removes the worktree directory via `git worktree remove --force` (if it exists)
   - Deletes the local branch via `git branch -d` / `git branch -D` (if it exists)
   - Deletes the remote branch via `git push origin --delete` (if it exists)
   All cleanup commands are guarded with `|| true` — failures do not abort the done-transition.

If the CWD verification fails, the SKILL stops immediately with an error. This prevents subsequent steps from operating on stale paths inside a deleted worktree.

## External Project Worktrees

Yoke manages items across multiple projects (YOK-562). When an item's `project` column references a non-yoke project, the worktree lifecycle operates on the external project's repository while Yoke's DB and merge locks remain in the Yoke repo.

### Path Resolution

The `projects` table stores per-project metadata:

| Column | Purpose |
|--------|---------|
| `repo_path` | Absolute path to the external project's git repository |
| `default_branch` | Base branch for the project (e.g., `main`, `develop`) |

**Create phase:** `create-worktree.sh --project <project-id>` resolves `repo_path` from `project-db.sh` and creates the worktree at `{repo_path}/.worktrees/YOK-{N}`. The base branch is resolved from the project's `default_branch`, falling back to `main`.

**Merge phase:** `merge-worktree.sh` auto-detects the project by parsing the item ID from the branch name, querying `items.project`, and looking up `repo_path` from the `projects` table. The target branch is also resolved from the project's `default_branch` unless explicitly overridden.

### Hook and DB Access

External worktrees live in a different git repository than Yoke. This creates a split between the code repo and the state repo:

- **Code operations** (branch, rebase, merge, PR, CI) run against the external project's repo (`REPO_ROOT` is set to `repo_path`).
- **State operations** (merge lock, item queries, status updates) always use the Yoke repo. `merge-worktree.sh` preserves the original repo root as `YOKE_REPO_ROOT` before overriding `REPO_ROOT` for the external project, ensuring all DB access and merge lock operations route to `yoke/yoke.db` in the Yoke repo.
- **Config** (`config-helper.sh`) reads from the Yoke repo's `yoke/config`, not the external project. Settings like `base_branch` and `max_active_worktrees` are Yoke-global; per-project overrides come from the `projects` table.

### Runtime DB Resolution Rule (YOK-1386)

**All state/DB operations MUST target the owning main-repo DB, even when
execution happens inside a linked worktree.** The canonical resolver chain is:

1. `YOKE_DB` env var (always respected if set).
2. `YOKE_ROOT` env var, normalized through
   `runtime.api.domain.worktree.resolve_yoke_root()` (YOK-1393).
   Handles both repo-root and state-dir shapes and strips
   `.worktrees/<branch>/` prefixes before appending `/yoke.db`.
3. `runtime.api.domain.db_helpers.resolve_db_path()` → delegates to
   `runtime.api.domain.worktree.resolve_db_path()` which strips
   `.worktrees/<branch>/` prefixes and resolves back to the main-repo
   `yoke/yoke.db`.

Runtime modules (engines, domain services, CLI tools) MUST NOT implement
bespoke `Path(__file__).parents[N] / "yoke" / "yoke.db"` fallbacks. Such
fallbacks resolve to the worktree-local path when the module executes inside a
linked worktree, which creates stray DB files and splits state. All DB path
resolution delegates to the shared `db_helpers.resolve_db_path()`.

If a stray `<worktree>/yoke/yoke.db` already exists, `yoke doctor` will
surface it via `HC-stray-db` with explicit migrate-before-remove guidance. The
implementation must not silently bind to that file as if it were the canonical
ledger.

### Merge Path Differences

The merge pipeline for external projects differs from Yoke-internal items in these ways:

1. **Repo root override** — `merge-worktree.sh` sets `REPO_ROOT` to the external project's `repo_path` so all git operations (rebase, push, PR creation) target the correct repository.
2. **Target branch** — Defaults to the external project's `default_branch` instead of Yoke's `base_branch` config value. An explicit `--target` flag still takes precedence.
3. **Safety stash** — Created in the external project's repo (since that is where the dirty files live).
4. **Merge lock** — Still acquired in the Yoke repo via `YOKE_REPO_ROOT`. This means external merges and Yoke merges share the same lock, preventing concurrent merge operations across projects.
5. **YOKE_REPO_ROOT sentinel** — The final output line prints the Yoke repo root (not the external project's), so the calling SKILL correctly `cd`s back to the Yoke main repo after cleanup.

## Orphaned Stash Detection

`/yoke doctor` (HC-orphaned-stashes) detects orphaned `yoke-pre-rebase-` stashes via `git stash list`. These indicate a merge that was interrupted and never recovered. Reported as WARN with the stash name so the operator can investigate.

Recovery: inspect the stash contents with `git stash show -p <ref>`, then either `git stash pop <ref>` to restore or `git stash drop <ref>` to discard.
