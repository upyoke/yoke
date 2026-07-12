# Shell Scripts Reference — Historical Archive

> **This file is the historical shell reference for Yoke. All scripts listed here have been deleted and replaced by Python entrypoints. See `docs/scripts.md` for the current Python entrypoints table.**

---


## Legacy reference (retired — historical only)

All scripts formerly lived in `.agents/skills/yoke/scripts/` (canonical). A compatibility symlink at `.claude/skills/yoke/` pointed to the canonical location. All scripts were POSIX sh (`#!/usr/bin/env sh`), no bashisms. All were executable.

**Python engine migration (YOK-1246):** Several scripts previously contained full shell implementations and were rewritten as thin launchers that delegated to Python domain modules or engines. In YOK-1370/YOK-1371 the thin launchers were deleted outright — callers now import the Python owner directly or invoke it as `python3 -m runtime.api....`.

## Unified DB Router

### yoke-db.sh
**Input:** `<domain> <subcommand> [args...]`
**Purpose:** Unified entry point for all Yoke DB operations. Dispatches to the correct domain script based on the first argument. Preferred in SKILL.md files over calling individual domain scripts directly. Auto-initializes the DB schema on every invocation.

Domains:
- `items` — Backlog item reads (`query-items.sh`) and writes (`backlog-registry.sh`)
- `epic` — Epic task management (`yoke-db.sh epic` → `runtime.api.domain.epic`)
- `projects` — Project domain: projects, sites, environments, capabilities (`project-db.sh`)
- `ouroboros` — Learning loop entries (`ouroboros-db.sh`)
- `shepherd` — Shepherd verdicts and conduct progress (`shepherd-db.sh`)
- `schema` — Schema migrations and initialization (`schema-db.sh`)
- `flows` — Deployment flow definitions (`flow-db.sh`)
- `events` — Structured event logging (`yoke-db.sh events` → `runtime.api.domain.events_crud`)
- `runs` — Deployment run lifecycle (`yoke-db.sh runs` → `runtime.api.domain.deployment_runs`)
- `release` — Release notes (`release-notes-db.sh`)
- `qa` — QA requirements, runs, and artifacts (`yoke-db.sh qa` → `runtime.api.domain.qa`)
- `sections` — Item sections CRUD (`item_sections` table, YOK-762)
- `designs` — Design documents (`designs-db.sh`)
- `envs` — Ephemeral environments (`env-db.sh`)
- `merge` — Merge lock management (`merge-lock.sh`)
- `query` — Raw SQL escape hatch against `$YOKE_DB`
- `init` — Initialize DB schema
- `help` — Print domain list or domain-specific subcommands

Key behavior:
- Auto-initializes DB schema via `schema-db.sh init` on every invocation
- Uses `exec` for dispatch — no extra process overhead
- Worktree-aware DB path resolution accepts either repo-root or concrete `yoke/` values for `$YOKE_ROOT`, normalizes through the canonical resolver, then falls back to `$CLAUDE_PROJECT_DIR/yoke` or git root with `.worktrees/` stripping
- `sections upsert` / `sections delete` immediately rerun `render-body.sh`; if rerendering fails, the command exits non-zero after the section row mutation so stale body state stays visible and GitHub sync is skipped
- `query` domain provides raw SQL escape hatch with optional `-separator` flag
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

## Orchestration Scripts

### update-status.sh
**Input:** `<epic-slug> <task-num> <new-status> [note]`
**Purpose:** Atomic DB-native task status update for epic tasks. Updates `epic_tasks`, emits a `TaskStatusChanged` event, rebuilds `data/BOARD.md`, syncs GitHub labels/comments, closes task issues on terminal states, and auto-unblocks dependent tasks.

Key functions:
- Status field update via `yoke-db.sh epic task-update-field`
- History row insert via `yoke-db.sh epic history-insert`
- `dispatch_attempts` auto-increment on `in_progress` transition
- `auto_unblock()` — after `completed`/`done` transition, scans blocked tasks in same epic, unblocks if all deps met (recursive)
- Label creation (idempotent, retains `2>/dev/null || true`)
- `_log_github_failure()` — appends structured failure lines to `yoke/.github-retry.log` with advisory locking
- `_is_dry_run()` — checks `YOKE_DRY_RUN=1` env var; skips GitHub writes when set

Error handling:
- GitHub write failures (label swap, comment post, issue close) are captured via `|| _rc=$?` pattern (compatible with `set -e`), logged to `yoke/.github-retry.log`, and the script continues (graceful degradation — always exits 0).
- Retry log format: `{ISO-8601-UTC} FAIL {action} #{issue-number} {error-snippet}` where action is one of: `label-swap`, `comment-post`, `issue-close`.
- Retry log writes use advisory locking via `lock-helper.sh` for parallel safety.

YOKE_DRY_RUN support:
- When `YOKE_DRY_RUN=1` is set, all GitHub write calls are skipped (with `[DRY-RUN]` messages). Local status updates still proceed normally. Follows the same pattern as `backlog-registry.sh`.

Cross-project support (YOK-683):
- All `gh issue` calls (label swap, comment post, issue close) use `-R` flag via `_resolve_item_repo()` to target the correct repository for the item's project.
- Historical per-project token resolution has been absorbed by the canonical project GitHub auth resolver.
- Sources `sync-helper.sh` for project-aware helper functions.

### sync-to-github.sh
**Input:** `<epic-name> <epic-dir>`
**Purpose:** Creates GitHub issues for epic + tasks, links via sub-issues (or checkbox fallback), creates status JSONs with local task IDs, generates dispatch chain rows in the DB. Task files keep their local plan-order IDs (no rename). Reads backlog item data from SQLite DB; writes `github_issue` back via DB update. Epic task file operations still use `yaml-helper.sh`. The `--backfill-titles` and `--backfill-labels` entrypoints are now thin flag shims into `runtime.api.domain.epic_task_sync`.

Key functions:
- `_is_backlog_item()` — returns 0 if the argument is a backlog item reference, used to branch between DB and YAML code paths
- `extract_metadata()` — for backlog items reads from DB; for task files parses YAML frontmatter (preferred) or falls back to sed-chain parsing for legacy files
- `strip_frontmatter()` — for backlog items writes DB body to temp file; for task files removes YAML block from issue body
- `resolve_deps()` — formats local task IDs as JSON array for epic task dependencies
- `ensure_label()` — auto-creates labels before issue creation
- `--backfill-titles <epic-ref>` — thin shim into `runtime.api.domain.epic_task_sync backfill-titles`, which updates open task issue titles to include zero-padded task numbers
- `--backfill-labels <epic-ref>` — thin shim into `runtime.api.domain.epic_task_sync backfill-labels`, which reconciles `type:task`, `status:*`, and `worktree:*` labels from DB state
- Dispatch chain generation per worktree (queues use local task IDs)
- Idempotent: skips tasks with existing status JSONs, uses `_epic_issue` sentinel for epic reuse
- DB bootstrap guard: auto-initializes `yoke.db` if missing via `schema-db.sh init` + `migrate-to-sqlite.sh`
- **Cross-project support (YOK-683):** Epic-level `gh issue` calls (label addition, body sync) used `-R` flag via `_resolve_item_repo()` and the then-current per-project token helper. Current Python callers use the canonical project GitHub auth resolver.

### merge-worktree.sh
**Input:** `<branch> [target-branch] [worktree-plan.md]`
**Purpose:** Rebase worktree branch onto target, auto-resolve generated files, run tests, create PR, wait for CI, merge, cleanup.

Key functions:
- `_check_and_clean_root_dirty_state()` — Classifies dirty files in `$REPO_ROOT` using `classify_dirty_files()` from `classify-dirty-files.sh` (YOK-501). Yoke-managed files are auto-committed with message `chore: auto-commit Yoke bookkeeping before merge [${BRANCH}]`. User-authored files block the merge (exit 4). Reads `$REPO_ROOT`, `$BRANCH` from environment.
- `_is_branch_modified_file(file)` — Branch-aware file check (YOK-538). Checks whether a file was intentionally modified on the branch relative to the merge base by looking it up in `$BRANCH_CHANGED_FILES`. Returns 0 if the file was modified by the branch, 1 otherwise. Uses `grep -qxF` for exact line matching (not glob). Called by `_auto_resolve_conflicts()` and the trial merge classification loop to distinguish intentional doc changes from drift.
- `_is_additive_conflict(file)` — Additive-conflict classifier (YOK-1205). Uses git merge stages (:1=base, :2=ours, :3=theirs) and diff to determine if a conflict is purely additive — both sides only added lines with no deletions from base. Returns 0 if provably additive, 1 otherwise. Used by both the trial merge classification loop and `_auto_resolve_conflicts()`.
- `_resolve_additive_conflict(file)` — Additive-conflict resolver (YOK-1205). Uses `git merge-file --union` to merge both sides' additions, then verifies no content was lost. Returns 0 on success. Only called for files that passed `_is_additive_conflict()`.

Key variables:
- `YOKE_MANAGED_PATTERNS` — Defined in `classify-dirty-files.sh` (YOK-501). Space-separated glob patterns for Yoke-managed files. Used by all classification sites via shared helper functions.
- `BRANCH_CHANGED_FILES` — Newline-separated list of files the branch intentionally modified relative to the merge base (YOK-538). Computed via `git diff --name-only $(git merge-base HEAD origin/${TARGET}) HEAD` before the trial merge begins (while the branch ref is still clean). Used by `_is_branch_modified_file()` to make doc conflict resolution branch-aware. Contains exact file paths (not globs).

Key behavior:
- Dirty-state classification via `classify-dirty-files.sh`: matches `YOKE_MANAGED_PATTERNS` glob patterns. `data/BOARD.md` is always Yoke-managed.
- Repo-root dirty-state classification and auto-commit before any worktree operations
- Multi-commit rebase loop (max 50 passes) for auto-resolvable file conflicts (generated files)
- Generated file conflicts: auto-resolved with `git checkout --theirs` (keep main's version)
- Branch-aware doc conflict resolution (YOK-538): doc files (`CLAUDE.md`, `yoke/README.md`, `yoke/docs/*`) are auto-resolved by keeping main's version only when the branch did not intentionally modify them. If the branch modified a doc file (file appears in `BRANCH_CHANGED_FILES`), the conflict is NOT auto-resolved — a warning is logged and the file is treated as a non-auto-resolvable conflict, triggering the merge-commit fallback or manual resolution diagnostic. This prevents silent data loss when a branch's purpose is to fix documentation. The branch-aware check is applied in both the trial merge classification loop and `_auto_resolve_conflicts()`.
- `GIT_EDITOR=true git rebase --continue` to avoid editor prompts
- Additive-conflict auto-resolution (YOK-1205): when a non-generated code/test file has conflicts where both sides only added lines (no deletions from base), the conflict is auto-resolved via `git merge-file --union`, preserving all content from both sides. The additive classifier is one signal; when it cannot prove a conflict is additive, the conflict is classified as "overlapping (needs agent judgement)" and the script exits 3 with structured `CONFLICT|file|classification` output on stderr for agent-assisted resolution.
- Non-generated file conflicts that are not provably additive exit with code 3 (agent-resolvable) instead of code 1, with structured per-file conflict classification on stderr
- Post-merge: updates all completed tasks in worktree to `done` status

### done-transition.sh
**Input:** `<item-number> [--env <env-name>] [--skip-simulation]`
**Purpose:** Automate the done-transition ceremony for backlog items. Orchestrates worktree merge (via `merge-worktree.sh`), status update, GitHub sync, board rebuild, and optional deployment tracking. Called by `/yoke usher` (not directly by advance — advance redirects to usher for done transitions).

Key behavior:
- **Step 6 retry loop (YOK-442):** The critical status update retries up to 3 times with 2-second backoff. On each non-zero exit from `backlog-registry.sh`, verifies whether the DB status was actually updated (non-zero exits often come from downstream GitHub sync, not the DB write). Only retries when the status genuinely failed to update.
- **Deployment flow guard (YOK-576):** If the item has a `deployment_flow` set and `deploy_stage` is not `complete`, exits with code 6. This prevents callers from bypassing the deployment pipeline managed by the Usher skill. The guard is a no-op for items without a deployment flow and gracefully degrades when the `deployment_flow`/`deploy_stage` columns do not exist (pre-YOK-563).
- **Integration simulation gate (YOK-395):** Epic items require a passing integration simulation before marking done. Use `--skip-simulation` to bypass.
- **Idempotent reruns:** If status=done and worktree is cleared, exits 0 immediately. If merge completed but status update failed, resumes from Step 6.

Exit codes:
- `0` — success (or idempotent re-run)
- `1` — merge failure or status update failed after retries
- `2` — CWD enforcement or argument error
- `3` — blocked before done: integration simulation gate failure (epic items) or merge conflicts requiring agent resolution
- `4` — user files at risk during merge
- `6` — deployment flow guard (item has deployment_flow but deploy_stage is not complete)

## Verification Scripts

### check-hard-blocks.sh
**Input:** `<item-id>` (`YOK-N` or bare numeric ID)
**Purpose:** Shared gate-aware dependency evaluator (YOK-1161, YOK-1190, YOK-1194). Reads `item_dependencies` where the given item is the dependent, evaluates each row's `gate_point` and `satisfaction`, and reports any unresolved blockers. Supports `--gate-point` filter. `fact:merged` prefers the canonical `items.merged_at` fact, falls back to branch ancestry when available, then falls back to `release`/`done` status when no stronger merge fact is available. Used by `advance/preflight.md`, `conduct/SKILL.md`, `conduct/single-item.md`, and `usher/collect.md`.

Output:
- `BLOCKED|YOK-{M}|{status}|{title}|{gate_point}|{satisfaction}` — one line per unresolved blocker
- No output when no unresolved dependency blockers exist

Exit codes:
- `0` — no unresolved hard-block dependencies
- `1` — one or more hard-block dependencies remain unsatisfied
- `2` — usage error (missing/invalid item id)

Key behavior:
- Normalizes `YOK-` prefixes and leading zeros
- Ignores non-`hard-block` dependency rows
- Accepts an optional `--gate-point <activation|integration|closure>` filter
- Orders blocker output by `blocking_item` for stable operator output and tests

### check-prerequisites.sh
**Input:** None (reads environment)
**Purpose:** Validates Yoke prerequisites: gh installed + authenticated, git version, directory structure, agent files, settings.json, .gitignore, CLAUDE.md. Outputs status table.

### verify-overlap.sh
**Input:** `<worktree-plan-file>`
**Purpose:** Checks that tasks in different worktrees don't modify the same files. Excludes generated files. Also verifies logical dependency groups — files declared as logically coupled must all be in the same worktree. Exits 1 on file overlap or logical conflict.

### validate.sh
**Input:** `<epic-name>`
**Purpose:** 5 deterministic integrity checks:
1. Status ↔ task file cross-reference
2. Worktree existence via `git worktree list`
3. GitHub issue label consistency
4. Dashboard status count comparison
5. Dispatch chain validity + stale detection (30-min threshold)

### validate-buzz-pipeline.sh
**Input:** `[--verbose]`
**Purpose:** Pre-flight validation for Buzz end-to-end pipeline. Checks that all prerequisites for the full Buzz lifecycle (idea through usher) are in place: project DB record, deployment flow, capabilities, token, SSH connectivity, and GitHub Actions workflows.

Exit codes: 0 = all checks passed, 1 = one or more checks failed

### discovery-scan.sh
**Input:** `<item-number>`
**Purpose:** Standalone discovery scan for done-transition gate. Writes item-scoped unreviewed ouroboros entries to a persistent file at `/tmp/discovery-scan.YOK-{N}.{PID}` whose path is printed as the last line of stdout.

### prd-validate.sh
**Input:** `<backlog-id>`
**Purpose:** Pre-planning quality gate for PRD validation. Validates that a backlog item body (PRD) meets minimum quality standards before the Architect runs. Checks structural completeness, acceptance criteria, and scope clarity.

## Worktree Scripts

### create-worktree.sh
**Input:** `<id-number> [base-branch] [--project <project-id>]`
**Purpose:** Creates a git worktree for any backlog item (issue or epic). Unified worktree creator that handles both Yoke-native and external project worktrees. Branch: `YOK-{N}`, Directory: `.worktrees/YOK-{N}`. Idempotent — reuses existing worktree if present.

Key behavior:
- Strips `YOK-` prefix if provided (accepts both `42` and `YOK-42`)
- `--project <project-id>` flag (YOK-562): resolves `repo_path` and `default_branch` from `project-db.sh` for external projects. Without `--project`, uses current git repo.
- Enforces `max_active_worktrees` config limit (default: 5)
- Session timing instrumentation via `timing-helper.sh`
- Main repo root detection handles linked worktrees via `--git-dir` / `--git-common-dir` comparison
- Exit 0 on success, prints worktree path to stdout

### install-worktree-deps.sh
**Input:** `<worktree-path> [project-id]`
**Purpose:** Auto-install project dependencies in a worktree after creation. Detects dependency files and runs the appropriate install command. Supports convention-based detection (package-lock.json, yarn.lock, requirements.txt, etc.) and project-level override via `setup_command` project capability.

Exit codes: 0 = success or no deps found, 1 = install failure

### resolve-playwright-cache.sh
**Input:** `[project-id] [worktree-path]`
**Purpose:** Canonical Playwright browser cache path resolver (YOK-1052). Single source of truth for `PLAYWRIGHT_BROWSERS_PATH`. Used at both install-time and runtime to ensure the same cache is used.

Resolution order:
1. `PROJECT_ID` set → `~/.yoke/playwright-cache/$PROJECT_ID` (stable per-project)
2. `WORKTREE_PATH` set → `$WORKTREE_PATH/.playwright-cache` (worktree-local)
3. Neither set → empty (caller should not export)

## Progress Scripts

### sync-progress.sh
**Input:** `<epic-ref> [task-id]` (task ID optional; e.g. `001`)
**Purpose:** Thin launcher into `runtime.api.domain.epic_task_sync progress` for epic-task progress-note GitHub sync. Posts unsynced `epic_progress_notes` rows as issue comments, marks them synced in the DB after successful post, and uses project-aware `-R` routing plus per-project token resolution for non-default repos.

### sync-task-label.sh
**Input:** `<epic-id> <task-num> <new-status>`
**Purpose:** Thin launcher into `runtime.api.domain.epic_task_sync label` for epic-task GitHub status-label sync (YOK-990). Reconciles the `status:*` label on the task's GitHub issue to match the new status. Removes stale labels and adds the correct one. Non-fatal: always exits 0; errors emitted to stderr. Called by the Python-owned `yoke-db.sh epic task-update-status` path after every status change.

### sync-task-body.sh
**Input:** `<epic-id> <task-num>`
**Purpose:** Thin launcher into `runtime.api.domain.epic_task_sync body` for epic-task GitHub body sync (YOK-1134). Pushes the authoritative `epic_tasks.body` value to the task's GitHub issue. Returns `0` on success/no-op and `1` on real sync failure so repair callers can decide whether to stop.

## Hook Scripts

### lint-sqlite-cmd.sh
**Input:** JSON on stdin (PreToolUse payload with `tool_name`, `tool_input`, etc.)
**Purpose:** PreToolUse hook for Bash commands. Enforces 12 safety checks:

1. **Block direct sqlite3 calls (YOK-273):** Agents must use `yoke-db.sh` or wrapper scripts. Allowlist covers scripts with "sqlite3" in their filename. Read-only commands referencing sqlite3 are allowed.
2. **Block `!=` and escaped SQL operators:** zsh histexpand converts `!=` to `\!=`. Also blocks `\>=`, `\<=`, `\>`, `\<`. Use `<>` for not-equal.
3. **Block direct calls to guarded scripts (YOK-299):** `backlog-registry.sh`, `schema-db.sh`, `merge-worktree.sh` must only be called via `yoke-db.sh` or `done-transition.sh`. Suppressed with `# lint:no-guard-check`.
4. **Block BSD-incompatible awk negation (YOK-352):** `!var` fails on macOS BSD awk. Use `var==0`.
5. **Block claude CLI invocations (YOK-367):** Nested Claude Code sessions crash the parent. Use the Agent tool instead.
6. **Block gh issue/pr without -R flag (YOK-680):** Denies the command with a warning message because cross-project items need explicit repo targeting. Suppressed with `# lint:no-repo-flag`.
7. **Block git commit/add with conflict markers (YOK-701):** Defense against committing corrupted Yoke files.
8. **Block wrong SQL column names (YOK-870):** Detect common column name mistakes when the table is identifiable. Suppressed with `# lint:no-column-check`.
8b. **Dynamic schema validation (YOK-932):** Supplement static blocklist with `PRAGMA table_info` queries against actual DB schema.
9. **Block direct status=done writes (YOK-950):** Must go through `done-transition.sh`. Suppressed with `# lint:no-done-check`.
10. **Block direct yoke-db.sh qa browser_substrate run-add (YOK-1014):** Browser QA runs must come from `browser-run-scenario.sh`.
11. **Block DDL in `yoke-db.sh query` (YOK-1026):** Denies the command with a migration-protocol warning when ALTER/CREATE/DROP TABLE appears in the raw query escape hatch. Suppressed with `# lint:no-ddl-check`.
Output: JSON with `permissionDecision: "deny"` if blocked; exit 0 if clean.

### lint-main-commit.sh
**Input:** JSON on stdin (PreToolUse payload with `tool_name`, `tool_input`, etc.)
**Purpose:** PreToolUse hook for Bash commands. Blocks `git commit` on `main` when staged files include implementation code and active items exist (YOK-733). Enforces the worktree discipline rule: implementation work belongs in worktrees, not on main.

Bookkeeping allowlist (always allowed on main):
- `yoke/ouroboros/**` — health reports, wrapups (gitignored since YOK-1157)
- `yoke/flows.md` — generated flows view
- `yoke/designs/**` — generated design views (gitignored since YOK-1157)
- `yoke/projects/*/qa-artifacts/**` — browser QA screenshots (gitignored since YOK-1157)
- `CLAUDE.md` — project instructions
- `.claude/**` — Claude config/skills/hooks

Key behavior:
- Only triggers on `git commit` commands targeting the `main` branch
- Only triggers when at least one active item exists in the DB
- If ALL staged files match the bookkeeping allowlist, the commit is allowed
- Bypass: add `# lint:no-main-check` comment to the command
- Output: JSON with `permissionDecision: "deny"` if blocked; exit 0 if clean

### lint-write-path.sh
**Input:** JSON on stdin (PreToolUse payload)
**Purpose:** PreToolUse hook for Write tool. Blocks `$$` in file paths — the Write tool does not expand shell variables, so `$$` creates literal filenames that mismatch cleanup traps. Use `mktemp` instead.

### lint-tc-label.sh
**Input:** JSON on stdin (PreToolUse payload)
**Purpose:** PreToolUse hook for Bash and Write tools. Blocks sequential `TC-[0-9]+` labels in test files under `.agents/skills/yoke/scripts/tests/` and numeric-only HC test filenames (`test-doctor-hc[0-9]*.sh`). Named labels like `TC-blocks-direct-sqlite` are allowed. Bypass: `# lint:no-tc-label-check`.

### sqlite3-error-hook.sh
**Input:** JSON on stdin (PostToolUse payload)
**Purpose:** PostToolUse hook for Bash commands. Hard-stops on failed sqlite3 commands to prevent silent data corruption. Also detects row-count collapse in critical tables after DDL operations (YOK-1296) and emits FATAL-severity `DataLossDetected` events.

### hook-helpers.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** Shared library for Yoke hook scripts. Provides common utility functions used across PostToolUse, PostToolUseFailure, and SubagentStop hooks. Sourced by `on-agent-stop.sh`, `on-bash-complete.sh`, and `observe-tool.sh`.

Functions:
- `find_project_root` — Resolve the main repository root. In worktree contexts, `$CLAUDE_PROJECT_DIR` points to the worktree, not the main repo. This function always prefers the main worktree root (first entry from `git worktree list --porcelain`) because the DB and shared state live there. Falls back to `$CLAUDE_PROJECT_DIR` if git is unavailable.
- `resolve_yoke_db` — Resolve the canonical `yoke/yoke.db` path via `resolve-paths.sh`. Hook scripts MUST use this instead of manually constructing `"$PROJECT_ROOT/yoke/yoke.db"` (YOK-667). Requires `$SCRIPT_DIR` set before sourcing.
- `get_session_id` — Resolve the current session ID (cross-harness, YOK-1298). Precedence: `$YOKE_SESSION_ID` → `$CLAUDE_SESSION_ID` → `$CODEX_THREAD_ID` → `"unknown"`.
- `resolve_dispatch_context DB_PATH AGENT_DIR` — Look up the active dispatch chain for a worktree. Queries `epic_dispatch_chains` for a chain whose `worktree_path` matches `AGENT_DIR`. Returns pipe-delimited `epic_id|task_num|item_id`. Used by `observe-tool.sh` and `on-agent-stop.sh` for event enrichment.

Key behavior:
- POSIX sh, no bashisms
- Functions return values, never call exit (callers decide exit behavior)
- Idempotent: safe to source multiple times
- No side effects on source (only function definitions)
- Requires `$CLAUDE_PROJECT_DIR` (set by Claude Code hook runtime) and `git`

### observe-tool.sh
**Input:** JSON on stdin (PostToolUse or PostToolUseFailure payload)
**Purpose:** Structured event telemetry hook for tool-call completion/failure paths. Emits `ToolCallCompleted`, `ToolCallFailed`, or `ToolCallStructuredExit` events to the `events` table. Detects anomalies such as `nonzero_exit`, `generated_view_write`, `nested_cli`, `benign_failure`, and `structured_exit`. Single `python3` invocation for performance (<200ms). Always exits 0.

Key behavior:
- Buffers stdin before any processing (multi-hook composition safe)
- Accepts `--agent <type>` and `--hook-event <PostToolUse|PostToolUseFailure>` CLI args for attribution and hook-source routing
- Resolves dispatch context via `hook-helpers.sh` for `item_id`/`task_num` enrichment
- Failed `PostToolUse` invocations exit early without emission so the paired `PostToolUseFailure` hook emits the single canonical `ToolCallFailed` row (YOK-1170)
- Stores anomaly signals on the primary tool-call row via `anomaly_flags`; no separate `AnomalyDetected` event is emitted
- Graceful no-op if events table, python3, or yoke.db unavailable
- Uses `YOKE_EVENTS_CAPTURE` mode for test harness integration

### observe-tool-pre.sh
**Input:** JSON on stdin (PreToolUse payload — parsed for `tool_use_id`)
**Purpose:** PreToolUse hook for tool-call timing (YOK-1069, YOK-1082). Emits a lightweight `ToolCallStarted` row keyed by `tool_use_id`. The PostToolUse hook (`observe-tool.sh`) queries that row to compute `duration_ms`.

Key behavior:
- Emits `ToolCallStarted` only when the hook payload contains `tool_use_id`
- The started-row envelope carries `tool_use_id`, `tool_name`, and `session_id`
- `observe-tool.sh` later looks up the matching started row to compute `duration_ms`
- Always exits 0 (timing is best-effort, never blocks tool execution)

### emit-denial.sh
**Input:** Named flags: `--hook <name> --tool <name> --check-id <id> --reason <text>`
**Purpose:** Emit a `ToolCallDenied` event for PreToolUse hook denials. Called by lint hooks (`lint-sqlite-cmd.sh`, `lint-event-registry.sh`, `lint-write-path.sh`, `lint-main-commit.sh`, `lint-tc-label.sh`) before returning deny JSON. Fires a structured event so denials are queryable in the `events` table.

Key behavior:
- Fail-open: never blocks the deny response; all errors silently exit 0
- Low-latency: runs `emit-event.sh` in background (`&`) so the hook returns immediately
- Current payload is intentionally thin: hook, check_id, reason, and tool name. Richer correlation fields are tracked under `YOK-1322`.
- Always exits 0 regardless of emit success

### on-agent-stop.sh
**Purpose:** SubagentStop hook for all 8 agents. Self-discovers active task from the `epic_dispatch_chains` DB table using `$CLAUDE_PROJECT_DIR` (with `find_project_root()` fallback via `git worktree list`). Sets discovered task to `stopped` status as safety net. Emits `AgentSessionStopped` event via `emit-event.sh` with agent context (epic/task), final task status, and auto-commit metadata (YOK-407).

### on-bash-complete.sh
**Purpose:** PostToolUse hook for Engineer's Bash calls. Same self-discovery as on-agent-stop.sh. Calls `sync-progress.sh` when the discovered epic task is `implementing`, then cd's to project root first to fix relative path issues.

### git-pre-commit.sh
**Purpose:** Git pre-commit hook installed by `/yoke init`. Warning-only — warns when staged files have unstaged modifications, but always exits 0 and never blocks commits.

### harness-session-start.sh
**Input:** JSON on stdin (hook payload with optional `session_id` field)
**Purpose:** UserPromptSubmit hook for session startup orientation. Emits a `## Yoke Orientation` block to stdout on the first user prompt of each session, including the shared prompt doctrine, neutral bootstrap read list, recent commits, and BOARD.md content. Resolves session identity from `$CLAUDE_SESSION_ID` (preferred) or JSON payload. Emits `AgentSessionStarted` event via `emit-event.sh` (YOK-407). Registers the session via `service_client.py session-begin` when the model is known (YOK-1298).

Key behavior:
- **Fire-once:** Creates `/tmp/yoke-session-{session_id}` marker file; subsequent invocations in the same session exit silently
- **Shared doctrine/read list:** Calls the neutral bootstrap helper to render the compact `Prompt Doctrine` block and the ordered startup-read list from `runtime/harness/bootstrap-spec.json`
- **Event emission:** Emits `AgentSessionStarted` event to the `events` table (graceful no-op if events infrastructure unavailable)
- **Smart truncation:** Drops Done section first, then truncates to `startup_plan_lines` (configurable, default: 300 lines). Falls back to simple line-count truncation if board markers are absent or Python is unavailable.
- **Graceful degradation:** Every external command wrapped in `|| true`. Non-Yoke repos, missing files, and tool failures all produce silent exit 0 (no error output).
- **Project root detection:** Uses `$CLAUDE_PROJECT_DIR` with `git rev-parse --show-toplevel` fallback. Validates Yoke repo via `yoke.db`.

### harness-session-end.sh
**Input:** None (uses session marker chain)
**Purpose:** Stop hook for session shutdown (YOK-1290, YOK-1278). Resolves the current session ID via `hook-helpers.sh:get_session_id()` (cross-harness precedence, YOK-1271), checks whether an active session exists, and calls `harness-sessions-db.sh end --force` to release all work claims and mark the session as ended through the shared guarded end-session path. Always exits 0 — the Stop hook must never block conversation exit. No-ops when no session marker is found, the session is already ended, or the DB is unavailable.

## Harness Adapter Surfaces

Python entrypoints under `runtime/api/domain/` plus the data artifacts under `runtime/harness/{harness-id}/` together provide thin adapter layers for non-Claude harnesses. They are launchers and capability manifests, not shell CLIs — they bootstrap orientation and emit the identity contract that later `/yoke` commands consume. See [harness-adapter-template.md](harness-adapter-template.md) for the five-part adapter contract and [hook-parity-map.md](hook-parity-map.md) for hook availability by harness. All Codex adapter shell scripts (`yoke-entry.sh`, `bootstrap-helper.sh`, `resolve-model.sh`, `hooks/*.sh`, `open-app.sh`) were retired in the zero-shell waves (YOK-1300, YOK-1361..YOK-1371); the entries below are the only sanctioned Codex entry surfaces today.

### runtime/harness/bootstrap-spec.json

**Purpose:** Neutral machine-readable bootstrap contract (data only, not a script). Defines the ordered `required_files`, `required_commands`, and `recommended_files` that every harness bootstrap surface consumes. Python entrypoints such as `codex_entry.py` read it directly at startup.

### runtime/api/domain/codex_entry.py

**Purpose:** Python-owned wrapper-only entry launcher for Codex sessions. Loads the shared bootstrap orientation context, resolves manifest-backed identity values, and can emit sourceable exports (`YOKE_EXECUTOR`, `YOKE_PROVIDER`, `YOKE_MODEL`, `YOKE_ROOT`) for shell-managed wrappers. Downstream-path support is derived server-side from `runtime/harness/codex/manifest.json` rather than exported as `YOKE_SUPPORTED_PATHS` (YOK-1299).

**Usage:** `python3 -m runtime.harness.codex.codex_entry bootstrap`, `python3 -m runtime.harness.codex.codex_entry env`, `python3 -m runtime.harness.codex.codex_entry idea "title"`, `python3 -m runtime.harness.codex.codex_entry do`, `python3 -m runtime.harness.codex.codex_entry refine YOK-N`, or `python3 -m runtime.harness.codex.codex_entry polish YOK-N`.

### runtime/api/domain/codex_model.py

**Purpose:** Resolves the active Codex model for the current thread. Prefers an explicit `YOKE_MODEL` override, then hook-cached runtime metadata, then the live Codex session transcript keyed by `CODEX_THREAD_ID`. Prints the truthful runtime model label (for example `gpt-5.4`) or exits non-zero if it cannot be determined. Invoked internally by `codex_entry` and the Codex hook dispatch — operators should not call it directly.

### runtime/harness/codex/manifest.json

**Purpose:** Capability manifest (data only, not a script) declaring Codex adapter identity, `bootstrap.spec_path`, supported entrypoints (`/yoke idea`, `/yoke do`, `/yoke refine`, `/yoke polish`), downstream paths, and optional local affordances. Read by Yoke core for server-side `supported_paths` derivation (YOK-1299) and by `codex_entry.py` for identity resolution.

### runtime/api/domain/codex_hooks.py

**Purpose:** Python-owned hook dispatch for Codex hook-enhanced mode. Requires the `codex_hooks` feature gate (Codex >= 0.118.0-alpha.2). Invoked by `.codex/hooks.json` for `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, and `Stop`. Handles orientation rendering, session registration backfill, tool guardrails, and lifecycle cleanup. No tracked Codex shell hook scripts remain.

### runtime/api/domain/codex_open_app.py

**Purpose:** Python-owned Codex Desktop launcher. Enables `codex_hooks` at app start with `codex app --enable codex_hooks <repo-root>`. Replaces the broken repo-local `.codex/config.toml` path for the tested runtime.

### .codex/hooks.json

**Purpose:** Codex hook configuration file (analogous to `.claude/settings.json` hooks). Maps the current Codex hook registrations (`SessionStart`, `UserPromptSubmit`, `PreToolUse` with Bash matcher, `PostToolUse` with Bash matcher, `PostToolUseFailure`, `Stop`) to the Python hook dispatch above via `python3 -m runtime.harness.codex.codex_hooks <event>`. The tested-vs-untested split lives in [hook-parity-map.md](hook-parity-map.md); `Stop` is wired here but is not part of the verified Codex parity slice.

---

## Backlog Scripts

### backlog-registry.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh items <write-subcommand>`
**Purpose:** CRUD operations for backlog items. All writes go to the SQLite DB (`yoke.db` items table) via `item-db.sh`. Manages the `YOK-N` ID system via DB auto-increment (`.counter` file is retired).

Subcommands:
- `add [--dry-run] <title> <type> [status] [priority] [epic]` — Create new item. Inserts into DB via `insert_item`. Triggers board rebuild. `--dry-run` previews the item without DB writes or syncing to GitHub.
- `update <id-number> <field> <value>` — Update a field via `update_item_field` (DB). Validates type and priority values. Auto-updates `updated_at` timestamp. Triggers board rebuild. Raw body writes are not supported; `items.body` is a virtual rendered field (YOK-1383). Structured-field writes use `_render_and_sync()` for GitHub sync.
- `list [--status X] [--type X] [--priority X]` — List items with optional filters via `query_items_list` (DB query).
- `get-next-id` — Query `MAX(id)+1` from DB, return `YOK-N` string. Used by `/yoke idea`.
- `sync-item <id-number>` — Create a GitHub issue for a backlog item. Labels with `type:{type}` and `priority:{priority}`. Stores issue number in `github_issue` field (DB + .md). Idempotent: skips if already synced.
- `close-issue <id-number>` — Close the linked GitHub issue. Idempotent: skips if already closed or not synced. Used by `/yoke usher` (via `done-transition.sh`) when status reaches `done`.
- `post-comment <id-number> <old-status> <new-status>` — Post a status-change comment on the linked GitHub issue. No-op if item has no `github_issue`. Used by `/yoke advance`.
- `sync-body <id-number>` — Update the linked GitHub issue body from the local backlog item's markdown body (everything after YAML frontmatter). No-op if not synced or `gh` unavailable. Graceful degradation: returns 0 on failure with warning to stderr. Used by `/yoke advance` on every status change and by `/yoke idea` after body content is appended.
- `ingest-body` — **Removed in YOK-1323.** `items.body` is now a virtual rendered field. All content goes through structured field writes.
- `rebuild-board` — Trigger `rebuild-board.sh` to regenerate the `data/BOARD.md` board.

Internal functions:
- `_body_write_full` — **Removed in YOK-1323.** `items.body` is now a virtual rendered field. Use structured field writes instead.

Key behavior:
- DB source of truth: All CRUD writes go to `yoke.db` items table via `item-db.sh`
- `items.body` is a virtual rendered field (read on demand, not stored)
- Auto-discovers `backlog/` via `$CLAUDE_PROJECT_DIR` or walking up from cwd
- `add`, `update`, and `sync-item` trigger board rebuild after mutation
- `sync-item` and `close-issue` require `gh` CLI; `post-comment` silently skips if `gh` unavailable
- Sources `item-db.sh` for DB operations and `lock-helper.sh` for concurrency safety
- GitHub sync operations (`sync-item`, `close-issue`, `post-comment`, `sync-body`) are implemented in `sync-helper.sh` (sourced library) and called as functions by backlog-registry.sh
- Body is virtual (YOK-1383): `items.body` is a virtual rendered field, not stored in the DB. Read via `items get YOK-N body`. Raw body writes (`_body_write_full()`, `ingest-body`) were removed. All content goes through structured field writes via `_render_and_sync()`.

### query-items.sh
**Input:** `<subcommand> [args]` — `list`, `count`, `get YOK-N field`, `row YOK-N`
**Also accessible via:** `yoke-db.sh items <read-subcommand>`
**Purpose:** Shell read adapter that delegates to `service_client.py` item query commands. Builds CLI flags so agents never write SQL directly. Supports filters: `--status`, `--priority`, `--type`, `--frozen`, `--fields`. Pipe-delimited output, exit codes: 0=results, 1=no results, 2=usage error.

### item-db.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** SQLite CRUD helpers for the `items` table in `yoke.db`. Provides all DB operations for backlog items. Sourced by `backlog-registry.sh`, `sync-helper.sh`, and `query-items.sh`. (Note: `backlog-resync.sh` is now a thin launcher over the Python resync engine and no longer sources this file directly.)

Functions:
- `init_item_db` — Ensures DB and items table exist. Sets `YOKE_DB` and `YOKE_DB_ROOT`. Must be called before any other function. Resolves `yoke/` directory via three-tier fallback (YOKE_ROOT env -> CLAUDE_PROJECT_DIR -> git root, with worktree path stripping).
- `query_item <id-number> <field>` — SELECT single field from items table. Maps frozen: 0/1 to "false"/"true". Returns empty string for SQL NULL.
- `query_item_row <id-number>` — SELECT all fields as pipe-delimited row in canonical column order.
- `insert_item <id> <title> <type> <status> <priority> <flow> <rework_count> <frozen> <epic> <github_issue> <deployed_to> <worktree> <body> <created_at> <updated_at>` — INSERT with positional args. Uses Python parameterized query for body-safe multi-line content.
- `update_item_field <id-number> <field> <value>` — UPDATE single field + updated_at. Body-aware: when field="body", value is a file path. Maps boolean/null/integer types automatically.
- `update_item_multi <id-number> field1=val1 [field2=val2 ...]` — Single UPDATE SET for multiple fields in one transaction.
- `query_items_list [--status X] [--type X] [--priority X]` — SELECT with optional WHERE clauses. Returns pipe-delimited rows ORDER BY id ASC.

Key behavior:
- Requires `schema-db.sh` for DB initialization (reachable via `_ITEM_DB_SCRIPT_DIR` or PATH)
- Requires `sqlite3` CLI and `python3` for insert/body-update operations
- Worktree-safe: resolves to main repo DB even when sourced from a worktree
- All values mapped: "null" -> SQL NULL, "true"/"false" -> 1/0 for frozen, integer types for rework_count
- Busy timeout: all sqlite3 CLI calls use `-cmd ".timeout 5000"` and Python calls use `PRAGMA busy_timeout=5000` to prevent SQLITE_BUSY (exit 5) errors under concurrent access

### sync-helper.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** Shared GitHub sync functions used by `backlog-registry.sh` and `backlog-resync.sh`. Extracted to avoid code duplication between the CRUD registry and the bidirectional resync script. Reads item fields from the DB via `query_item` (from `item-db.sh`).

Functions:
- `sync_labels <id-number>` — Compare local status, priority, and type labels against the GitHub issue's labels. Removes stale labels and adds correct ones. Idempotent. No-op if `github_issue` is null or `gh` unavailable.
- `sync_item <id-number>` — Create a GitHub issue for a backlog item (if not yet synced). If already synced, delegates to `sync_labels` to update labels. Includes dedup check (searches for existing `[YOK-N]` prefixed issues). Labels with `type:{type}` and `priority:{priority}`.
- `post_comment <id-number> <old-status> <new-status>` — Post a status-change comment on the linked GitHub issue. Updates status labels. No-op if `github_issue` is null or `gh` unavailable.
- `close_issue <id-number>` — Close the linked GitHub issue. Ensures status label is applied. Idempotent: checks current state before closing.
- `sync_body <id-number>` — Update the GitHub issue body from the local backlog item's markdown body (strips YAML frontmatter). Graceful degradation: returns 0 on failure with warning to stderr.
- `reopen_issue <id-number>` — Reopen a closed GitHub issue. Idempotent: no-op if already open.
- `sync_frozen_label <id-number> <frozen-value>` — Thin wrapper into `runtime.api.domain.backlog_github_sync frozen-label`. Adds or removes the `frozen` label on the linked GitHub issue while preserving the sourced `sync-helper.sh` call surface for `backlog-registry.sh` and `backlog-resync.sh`.
- `_resolve_item_project <id-number>` — Look up the project for a backlog item. Returns the project value (e.g., `"buzz"`) or empty string for yoke/default. Used by all sync functions to derive per-project token.
- `_resolve_repo_for_epic_task <epic-id>` — Look up the repo for an epic task by resolving the parent backlog item's project. Returns the `owner/repo` string or empty for yoke default.
- Historical per-project token helper — Auth resolution moved to `runtime.api.domain.project_github_auth` in 2026; see `docs/OVERVIEW.md` for the current model.
- `_with_project_token <project> <command...>` — Execute a `gh` command with project-specific token in a subshell, preventing `GH_TOKEN` leakage between project iterations.

Key behavior:
- Reads item fields from DB via `query_item` (sourced from `item-db.sh`); no longer depends on `yaml-helper.sh` for field reads.
- Requires sourcing scripts to provide: `$GH_RETRY`, `$CONFIG_HELPER`, `$BACKLOG_DIR`, `$SCRIPT_DIR`, `$_COLOR_STATUS`, `$_COLOR_TYPE_EPIC`, `$_COLOR_TYPE_ISSUE`, `_is_dry_run()`, `read_field()`, `zero_pad()`.
- All functions respect `YOKE_DRY_RUN=1` (skip GitHub writes with `[DRY-RUN]` messages).
- All functions check `gh` CLI availability before making API calls.
- Uses `$GH_RETRY` for all GitHub operations (exponential backoff on rate limits).
- **Per-project token isolation (YOK-683):** The shell-era sync functions routed through the then-current per-project token helper before `gh` calls. Current Python paths enforce the same project scoping through the canonical project GitHub auth resolver.

### gh-issue.sh
**Input:** `<gh-subcommand> YOK-N [extra-args...]`
**Purpose:** Resolve YOK-N to GitHub issue number and forward to `gh` CLI. Utility wrapper that looks up the `github_issue` field from the DB and passes through to `gh issue <subcommand> <number>`. Example: `sh gh-issue.sh view YOK-42` → `gh issue view 123`.

### update-labels.sh
**Input:** None (reads `yoke/config`)
**Purpose:** Sync GitHub label colors from config. Reads all `label_color_*` settings and applies them to existing repo labels. Creates labels that don't exist yet. Safe to run repeatedly.

### backlog-resync.sh *(thin launcher → Python engine)*
**Input:** `[--detect-only | --fix] [--doctor-format]`
**Purpose:** Thin launcher that delegates to `python3 -m runtime.api.engines.resync` (YOK-1246 task 008). The Python engine implements bidirectional backlog-to-GitHub sync detection and repair. Three-stage pipeline: linkage, field comparison, repair. **Multi-repo support (YOK-683):** Iterates over each project in the `projects` table, fetches issues from each project's `github_repo`, and only compares items belonging to that project. Current credential routing is owned by the canonical project GitHub auth resolver.

Stages:
- **Stage 1: Linkage** — Per-project full outer join of local items (backlog + epic tasks) and GitHub issues. For each project, issues are fetched from the correct `github_repo` via `gh issue list --limit 999 --state all -R <repo>`. Produces three sets per project: paired items, local orphans (no GitHub issue linked), and GitHub orphans (`[YOK-` prefixed issues not linked from any local item). GitHub orphans labeled `yoke:orphan` are automatically skipped (known historical orphans). Backlog items are loaded via SQL query filtered by project (`SELECT id, github_issue FROM items WHERE project = ?`); epic tasks are still read from JSON status files. GitHub API data processed via inline Python.
- **Stage 2: Field comparison** — For paired items, compares title (after stripping `[YOK-N]` prefix), body (exact match after trimming trailing whitespace), labels (status, priority, type), open/closed state, frozen-label presence (local `frozen` flag vs GitHub `frozen` label), and comment presence (`**Status:**` marker for done items). All backlog field reads use `_query_item` (SQLite). Zero additional API calls — all comparisons use Stage 1 cached data.
- **Stage 3: Repair** (`--fix` mode only) — Fixes all detected drifts using `sync-helper.sh` functions: `sync_item` for local orphans, `sync_body` for body drift, `sync_labels` for label drift, `close_issue`/`reopen_issue` for state drift, `sync_frozen_label` for frozen-label drift, `post_comment` for missing status comments. Reports GitHub orphans without auto-fix. All repair operations target the correct project-specific repo.

Flags:
- `--detect-only` — (default) Detect drift and report. Exit 1 if any drift found, exit 0 if clean.
- `--fix` — Detect and repair all drifts. Exit 1 if any repair failed, exit 0 if all succeeded.
- `--doctor-format` — Output HC-missing-gh-issues through HC-comment-sync, HC-label-drift, HC-state-drift, and HC-frozen-label-drift as pipe-delimited records for `doctor.sh` consumption. Format: `HC-{N}|{label}|{PASS|WARN}|{detail}`.

Exit codes:
- `0` — No drift found (`--detect-only`) or all repairs succeeded (`--fix`).
- `1` — Drift found (`--detect-only`) or any repair failed (`--fix`).

Key behavior:
- Reads backlog item fields from `yoke.db` via inline `_query_item` helper (three-tier DB path resolution, bootstrap guard)
- Provides DB-backed `read_field()` compatibility shim for `sync-helper.sh` (until YOK-195 rewrites it)
- Single bulk API call for detection (Stage 1) — avoids per-item queries
- Handles backlog items via SQLite (epic task data also lives in DB tables)
- Temp files managed in `mktemp -d` directory with trap cleanup
- Graceful degradation: exits 0 with skip message when `gh` unavailable
- In `--doctor-format` mode, emits WARN records for all HC-missing-gh-issues-32, HC-label-drift, HC-state-drift, HC-frozen-label-drift when `gh` unavailable
- **Multi-repo iteration (YOK-683):** Iterates over each project from `projects` table, fetching issues from each project's `github_repo` with per-project token isolation via `_with_project_token()`

### rebuild-board.sh
**Input:** Optional `$1` = repo root path (auto-detected from `$CLAUDE_PROJECT_DIR` or cwd if omitted)
**Purpose:** Shell entrypoint for board rebuilds. Handles throttling, file locking (via `lock-helper.sh`), multi-board iteration, and file I/O. Delegates all rendering to the Python board renderer (`python3 -m runtime.api.board` from the `runtime/api/board/` package), which produces the art header, dashboard widgets, board sections, and project timelines widget. See `runtime/api/board/README.md` for renderer architecture and module details.

Called by:
- `update-status.sh` after task status changes
- `backlog-registry.sh` after `add`, `update`, and `rebuild-board` subcommands

Key behavior:
- Preserves everything outside `<!-- YOKE:BOARD:START/END -->` markers
- Creates markers if missing (appends to end)
- Creates `data/BOARD.md` from scratch if file doesn't exist
- Acquires a global board lock (`data/BOARD.md.lock`) via `lock-helper.sh` to prevent concurrent rebuilds from corrupting the file
- Uses temp files with PID suffixes for safe concurrent operation
- Rendering is delegated to the Python board renderer (`runtime/api/board/`), which handles art header (master map, frontier fill, rainbow modes, standalone variants), dashboard widgets, board sections with epic sub-rows, and the project timelines widget
- BOARD.md is 100% auto-generated (no human-maintained sections); per-item context goes in backlog item bodies

### preview-board-art.sh
**Input:** CLI flags: `--rainbow`, `--done N --active N --total N`, `--percent N`, `--variant N|NAME`, `--ascii N`, `--mixed N`, `--all`, `--stats A,P,B,D,F`, `--no-stats`, `--dashboard`, `--wip N`, `--zen`
**Purpose:** Standalone preview tool for visual QA of board header art. Renders to stdout without modifying BOARD.md. Most preview modes are synthetic and DB-free; `--zen` uses the live DB when available. The shell wrapper resolves repo/config/DB paths, then delegates all rendering to `python3 -m runtime.api.board preview`. Supports all rendering modes: progress fill, rainbow, specific variant by number or name, `--mixed N`, and `--all` for side-by-side comparison. The `--dashboard` flag renders mock dashboard rows. `--velocity-meter` adds the mock 4-row 90-day meter. `--zen` renders the project timelines widget from live DB data through the Python renderer.

## Ouroboros Scripts

### doctor.sh *(thin launcher → Python engine)*
**Input:** Optional `--file <path>` (default: `yoke/ouroboros/health/health-{YYYYMMDD}.md`), `--fix` (auto-repair trivial issues: label mismatches, stale dashboards, stale worktrees, GitHub open/closed state drift, missing status comments, bidirectional sync drift), `--only <slugs>`, `--quick`, `--project <name>`
**Purpose:** Thin launcher that delegates to the Python doctor engine at `runtime/api/engines/doctor` (YOK-1246 tasks 009-012). Resolves paths (`YOKE_ROOT`, `YOKE_DB`, `REPO_ROOT`) and invokes `python3 -m runtime.api.engines.doctor` with all CLI arguments passed through. All HC logic, DB queries, and report formatting live in the Python engine. 40+ deterministic health checks covering backlog consistency, GitHub sync, orphaned issues, worktree health, documentation drift, blocked items, dispatch chain integrity, backlog hygiene, agent prompt consistency, hook executability, per-epic validation, self-test, branch divergence, uncaptured discoveries, undeployed done items, schema validation, semantic drift, orphaned stashes, stale session files, untracked bug language, size/bloat monitoring, backlog quality, GitHub orphan detection, sprint DB integrity, orphaned sprint items, track manifest freshness, bidirectional GitHub sync (HC-missing-gh-issues-32, HC-label-drift, HC-state-drift, HC-frozen-label-drift delegated to `backlog-resync.sh`), orphaned temp files, session startup hook, path confabulation detection, SQLite DB integrity, config file validation, architectural consistency audit, documentation health audit (HC-doc-health), shepherd spec body integrity (HC-shepherd-spec-integrity), wrong-repo GitHub issue detection (HC-wrong-repo-issues, YOK-683), and template-to-project content drift (HC-template-project-drift, YOK-760). HC-orphaned-gh-issues and HC-gh-orphan-detection iterate per-project repo (YOK-683).

Health checks:
- HC-status-consistency: Backlog status consistency (`refined-idea` / `implementing` / `reviewing-implementation` epics have matching task rows)
- HC-orphaned-gh-issues: Orphaned GitHub issues (Yoke-labeled issues with no backlog item) — iterates per-project repo (YOK-683), skips if gh unavailable
- HC-worktree-health: Worktree health (dirty worktrees, stale branches)
- HC-doc-drift: Documentation drift (commit cross-reference — flags commits that changed source files without also updating docs)
- HC-blocked-items: Blocked items (>7 days WARN, >30 days FAIL)
- HC-dispatch-chain: Dispatch chain integrity (references, bounds, heartbeat freshness)
- HC-backlog-hygiene: Backlog hygiene (missing required frontmatter)
- HC-agent-consistency: Agent prompt consistency (hook scripts exist)
- HC-hook-executability: Hook script executability
- HC-epic-validation: Per-epic validation (runs validate.sh for each epic)
- HC-self-test: Self-test (runs check-prerequisites.sh)
- HC-branch-divergence: Local/remote branch divergence
- HC-uncaptured-discoveries: Uncaptured discoveries in recent commits
- HC-undeployed-done: Undeployed done items. (YOK-1131, YOK-1154) Evaluates per-project: resolves deployment environments from DB (`environments` via `sites` + `deployment_flows.target_env` + `project_capabilities`). No config-file fallback. Items whose project has no resolved environments are skipped. Configurable threshold via `deploy_warn_days`.
- HC-frontmatter-schema: Backlog frontmatter schema validation (type, status, priority, github_issue format, flow, rework_count; DB schema enforces valid columns)
- HC-claudemd-drift: CLAUDE.md semantic drift (stale convention claims, health check count)
- HC-orphaned-stashes: Orphaned pre-merge stashes (`yoke-pre-rebase-` entries in `git stash list`)
- HC-stale-sessions: Stale session files (`.session` files older than 4 hours in `yoke/sessions/`; gated by `session_registry_enabled` config flag)
- HC-untracked-bug-language: Untracked bug language in working notes (scans strategy/PAD.md, backlog item bodies, unreviewed ouroboros log entries for bug-adjacent keywords without YOK-N references; suppresses done items, frontmatter, reviewed entries, and lines with YOK-N)
- HC-size-bloat: Size/bloat monitor (checks backlog item and ouroboros log file sizes against configurable thresholds; warns on large files that may indicate unbounded growth)
- HC-backlog-quality: Backlog quality (stale idea items >30 days, titles too short <10 chars, empty bodies, missing priority; configurable via `backlog_stale_days`)
- HC-gh-orphan-detection: GitHub orphan detection (queries all GitHub issues with `[YOK-` prefix, compares against backlog `github_issue` fields and epic task status files, flags issues not linked from any backlog item or epic task) — iterates per-project repo (YOK-683), skips if gh unavailable
- HC-missing-gh-issues: Missing GitHub issues (backlog items with no linked GitHub issue). Delegated to `backlog-resync.sh --doctor-format`. `--fix` calls `sync-item` to create the issue.
- HC-title-drift: Title drift (GitHub issue title differs from local backlog item title). Delegated to `backlog-resync.sh --doctor-format`. Exact string comparison after stripping `[YOK-N]` prefix. `--fix` updates the GitHub title.
- HC-body-drift: Body drift (GitHub issue body differs from local backlog item body). Delegated to `backlog-resync.sh --doctor-format`. Exact body comparison after trimming trailing whitespace. `--fix` calls `sync-body` to push local body to GitHub.
- HC-reverse-completeness: Reverse completeness (GitHub issues with `[YOK-` prefixed titles not linked from any backlog item or epic task). Delegated to `backlog-resync.sh --doctor-format`. Report only — no auto-fix.
- HC-comment-sync: Comment sync (done items missing `**Status:**` comment on GitHub). Delegated to `backlog-resync.sh --doctor-format`. `--fix` posts a synthetic status comment via `post_comment`.
- HC-label-drift: Label drift (GitHub issue labels don't match local status/priority/type). Delegated to `backlog-resync.sh --doctor-format`. `--fix` calls `sync_labels` to reconcile labels.
- HC-state-drift: State drift (GitHub issue open/closed state doesn't match local status — `done`/`cancelled` expect CLOSED, all others expect OPEN). Delegated to `backlog-resync.sh --doctor-format`. `--fix` calls `close_issue` or `gh issue reopen`.
- HC-orphaned-temp-files: Orphaned temp files (scans project tree for `*.tmp.*` and `.sort_tmp.*` files older than 5 minutes, and `/tmp` for stale `rebuild-board.*`/`sync-to-github.*` directories older than 10 minutes). `--fix` mode removes orphans.
- HC-session-startup-hook: Session startup hook — verifies `.claude/settings.json` contains the `UserPromptSubmit` hook entry for `harness-session-start.sh`, that the script exists and is executable, and runs a smoke test (emits `## Yoke Orientation` header).
- HC-path-confabulation: Path confabulation detection — scans filesystem for known confabulated directories (`ouraboros/` misspelling, `yoke/yoke/` prefix doubling) and working notes (ouroboros log, patterns, strategy/PAD.md) for confabulated path references.
- HC-sqlite-integrity: SQLite DB integrity — runs `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on `yoke.db`.
- HC-config-validation: Config file validation — validates `yoke/config` entries against known keys and value formats. Supports dynamic key prefix `art_weight_rainbow_*` for rainbow per-variant weights (emoji/ASCII/mixed per-variant weights use inline `# weight:` comments, not config keys). Uses `[A-Za-z_][A-Za-z0-9_]*=` regex to skip non-config lines (like art grid data).
- HC-arch-consistency: Architectural consistency audit — cross-checks agent definitions, SKILL.md files, and scripts for structural consistency.
- HC-frozen-label-drift: Frozen label drift (GitHub issue labels for frozen items don't include `frozen` label). Delegated to `backlog-resync.sh --doctor-format`.
- HC-doc-health: Documentation health audit — four sub-checks: (1) missing `README.md` (FAIL), (2) broken internal doc links in `yoke/docs/*.md` (FAIL), (3) stale docs where source files are newer than the doc (WARN), (4) undocumented shipped features — done items with no keyword matches in docs (WARN). Not auto-fixable; requires manual attention.
- HC-shepherd-spec-integrity: Shepherd spec body integrity — detects epics that passed the `refined_idea_to_planning` shepherd transition (READY/CAVEATS verdict) but whose body contains only a Shepherd Log with no spec sections (Problem, Goals, Functional Requirements, Requirements, Technical Plan, Design Spec, Root Cause, Fix, Acceptance Criteria). Warns on PM specs that were lost or never written.
- HC-schema-drift: Schema drift detection — cross-checks DB schema against expected tables/columns.
- HC-stale-body: **Deprecated (YOK-1383).** `body_generated_at` no longer exists — body is now a virtual rendered field assembled on demand.
- HC-epic-task-worktree: Epic task worktree backfill — detects epic tasks missing worktree assignments.
- HC-orphaned-active-items: Orphaned in-flight items — detects merged or merge-complete items that never completed the done transition.
- HC-stale-remote-branches: Stale remote branches — detects remote branches that no longer have active work.
- HC-reviewed-implementation-epics-no-sim: Reviewed-implementation epics require an integration simulation record.
- HC-shepherd-lifecycle: Shepherd lifecycle enforcement (YOK-589) — epics past `refined-idea` must have shepherd verdicts (`refined_idea_to_planning` READY/CAVEATS for planning+, `planning_to_plan_drafted` READY/CAVEATS for planned+). Double-report prevention: if both are missing, only reports `refined_idea_to_planning`.
- HC-deferred-items: Deferred items enforcement (YOK-595) — scans done epics for: (1) UNFILED entries in `## Deferred Items` section, (2) deferral language in body text (e.g., "deferred to a follow-up", "isolated to a follow-up", "out of scope for this epic") without adjacent YOK-N references. Excludes content in fenced code blocks. WARN severity.
- HC-dependency-drift: Dependency drift detection (YOK-592) — detects items with non-empty `depends_on` values that lack corresponding `item_dependencies` rows. The `depends_on` column is deprecated; all dependency data should live in `item_dependencies`. This check is detect-only; any remaining rows should be repaired directly before the deprecated column is dropped.
- HC-projects-without-flows: Projects without deployment flows (YOK-563) — every project should have at least one `deployment_flow` defined. Checks `projects` and `deployment_flows` tables. WARN if a project has no flows.
- HC-incomplete-deploy-stage: Done items with incomplete deploy_stage (YOK-563) — items that are done and have a `deployment_flow` but `deploy_stage` is not `'complete'`. WARN severity.
- HC-wrong-repo-issues: Wrong-repo GitHub issues (YOK-683) — validates that each item's `github_issue` exists in the repository matching the item's `project`. Detects issues created in the wrong repo (e.g., a buzz-project item whose GitHub issue exists in `upyoke/yoke` instead of `example-org/buzz`). Uses `_resolve_item_repo()` to determine expected repo, then verifies via GitHub API. Checks both the expected repo and the default yoke repo to identify misplacement. WARN severity. Skips if `gh` unavailable.
- HC-template-project-drift: Template-to-project content drift (YOK-760) — re-renders each project's workflow and scaffold files via `render-project.sh` in dry-run mode (no `--write`), then diffs the rendered output against the tracked files in `projects/{project}/workflows/` and `projects/{project}/scaffold/`. Reports WARN if any tracked file differs from what the render pipeline would produce. Detects: manual edits to tracked files, template changes not re-rendered, placeholder values that changed. Fix: run `render-project.sh {project} --write` to resync. Iterates all projects with a `config` file in `yoke/projects/`.
- HC-event-registry-coverage: Event registry coverage (YOK-431) — checks for stale active entries (registered but not emitted in 30 days) and rogue events (emitted in 30 days but not in `event_registry`). Gracefully skips if `event_registry` table is not present.
- HC-event-emission-rate: Event emission rate (YOK-431) — verifies events are being emitted when agent sessions are active. WARN if 0 events emitted in 24h despite active dispatch chains or shepherd verdicts. Gracefully skips if no sessions ran in the past 24h.
- HC-event-callsite-registry-sync: Event call site registry sync (YOK-431, YOK-1240) — reuses `yoke-db.sh events registry discover` (shared discovery path covering scripts, SKILL files, and API code) to find call sites, then checks each against the `event_registry` table. WARN if any call site emits an unregistered event name. Gracefully skips if `event_registry` table is not present.
- HC-orphaned-runs: Orphaned deployment runs (YOK-831) — detects `deployment_runs` with status `created` or `executing` that have no items in `deployment_run_items`. A run with zero enrolled items is invalid. WARN severity.
- HC-stale-runs: Stale deployment runs (YOK-831) — detects `deployment_runs` stuck in `executing` status for more than 24 hours. May indicate a pipeline that stalled without completing or failing. WARN severity.
- HC-run-item-status-consistency: Run-item status consistency (YOK-831) — detects items enrolled in an active deployment run (status `executing`) whose item status is not `release`. Items in an executing run must be at `release`. FAIL severity.
- HC-run-qa-unsatisfied: Run QA unsatisfied (YOK-831) — detects `deployment_runs` with status `succeeded` that still have unsatisfied blocking QA requirements in `deployment_run_qa` (status `pending` or `failed` with `blocking=1`). Items in these runs cannot transition to `done`. WARN severity.
- HC-preview-occupancy-stale: Preview environment occupancy stale (YOK-831) — detects entries in `deployment_preview_environments` with status `active` whose associated deployment run has already completed (`succeeded`, `failed`, or `cancelled`). May indicate a preview environment that was not properly released. WARN severity.

Output: Branded "Ouroboros Health Report" with PASS/WARN/FAIL per check. Exit 0 if no FAILs, exit 1 if any FAILs.

### ouroboros-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh ouroboros <subcommand>`
**Purpose:** SQLite CRUD wrapper for `ouroboros_entries` and `wrapup_reports` tables in `yoke/yoke.db`. Manages Ouroboros learning loop data: agent observations (problems, friction, ideas, cross-critiques) and end-of-session wrapup reports. Same pattern as `release-notes-db.sh`. POSIX sh, uses `sqlite3` and `python3`.

Subcommands:
- `insert-entry <timestamp> <agent> <context> <category> <body>` — Insert one observation entry via positional args. Deduplicates by timestamp+agent+category+body (skips silently if duplicate exists). Echoes the inserted row ID on success.
- `insert-entry --body-stdin <timestamp> <agent> <context> <category>` — Insert one observation entry with body read from stdin. Preferred for LLM-constructed commands where body content may contain shell-unsafe characters. Same dedup behavior as positional-arg form.
- `insert-entry --agent <a> --category <c> [--context <x>] [--timestamp <t>] --observation <o>` — Insert via named flags. Timestamp auto-generated via `_now_iso` if `--timestamp` omitted. `--context` is optional. Named-flag mode is triggered when at least one recognized semantic flag (`--agent`, `--context`, `--category`, `--observation`, `--timestamp`) is present.
- `insert-entry --body-stdin --agent <a> --category <c> [--context <x>] [--timestamp <t>]` — Named flags + body from stdin. `--body-stdin` and `--observation` are mutually exclusive (exit 2 if both given). Flags may appear in any order.
- `insert-wrapup <session_timestamp>` — Insert a wrapup report with body read from stdin. Deduplicates by `session_timestamp` (skips if report for that timestamp already exists). Echoes the inserted row ID on success.
- `list-entries [--unreviewed]` — List entries as pipe-delimited rows (id|timestamp|agent|context|category|body|reviewed|archived). Body newlines are collapsed to spaces for single-line output. `--unreviewed` filters to entries where `reviewed IS NULL`.
- `list-wrapups` — List wrapup reports as pipe-delimited rows (id|session_timestamp|body|created_at). Body newlines are collapsed to spaces.
- `mark-reviewed <id>` — Set the `reviewed` field to the current ISO 8601 timestamp for the entry with the given id. Exit 1 if entry not found.
- `mark-archived [--all-reviewed] | [<id>]` — Archive entries. `--all-reviewed` archives all entries that have been reviewed but not yet archived. `<id>` archives a single entry by id. Sets `archived` field to current ISO 8601 timestamp.
- `generate-wrapup <session_timestamp>` — Render a wrapup report as a markdown file at `yoke/ouroboros/wrapups/wrapup-{session_timestamp}.md`. Reads the report body from the `wrapup_reports` table. Exit 1 if report not found.

Validation (named-flag mode):
- `--agent` and `--category` are required; exit 2 with usage message if missing
- Either `--observation` or `--body-stdin` must be provided; exit 2 if neither given
- `--body-stdin` and `--observation` are mutually exclusive; exit 2 if both given
- Unrecognized flags (any `--`-prefixed argument not in the recognized set) cause exit 2 with an error naming the unknown flag

Key behavior:
- Worktree-aware DB path resolution accepts either repo-root or concrete `yoke/` values for `$YOKE_ROOT`, normalizes through the canonical resolver, then falls back to `$CLAUDE_PROJECT_DIR/yoke` or git root with `.worktrees/` stripping
- Auto-initializes tables via `schema-db.sh init` if DB is missing
- All inserts use Python parameterized queries for body-safe multi-line content
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

- Exit 0 on success, 1 on error

## Event Telemetry Scripts

### yoke-db.sh events *(thin launcher → Python domain module)*
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh events <subcommand>`
**Purpose:** Thin launcher delegating to `runtime.api.domain.events_crud` (YOK-1246 task 004). All domain logic (CRUD, registry, pruning, severity config) lives in the Python module. This file exists solely to preserve the `sh "$SCRIPT_DIR/yoke-db.sh" events` calling convention. Manages structured event logging data: agent tool call telemetry, session lifecycle events, anomaly detection, and event registry governance.

Subcommands:
- `init` — Create `events` and `severity_config` tables with indexes (idempotent). Indexes on: `event_id` (UNIQUE), `source_type`, `session_id`, `event_name`, `created_at`, `trace_id`, `project`, `tool_name`, and composite `(event_kind, event_type)`.
- `insert [positional | --flags]` — Insert an event row. Supports both positional args and named flags. Uses `INSERT OR IGNORE` on `event_id` for deduplication.
- `list [filters]` — List events (pipe-delimited), filterable by `--source-type`, `--session-id`, `--event-kind`, `--event-name`, `--agent`, `--service`, `--trace-id`, `--project`, `--min-severity`, `--since`, `--until`.
- `query <sql>` — Pass-through SQL query on events.
- `count [filters]` — Count events with same filters as `list`.
- `anomalies [filters]` — Events where `anomaly_flags IS NOT NULL`. Same filters as `list`. Output is consumable by `/yoke curate`.
- `prune [--dry-run]` — Per-severity retention pruning: DEBUG 7d, INFO 30d, WARN 90d, ERROR/FATAL forever.
- `tail [N|--limit N]` — Most recent N events (default 20).
- `severity-config set <event_kind> <event_type> <min_severity>` — Set write-side severity threshold.
- `severity-config list` — List all severity config entries.
- `registry add <name> --kind K --type T --service S --description D [opts]` — Register event type (INSERT OR IGNORE — idempotent).
- `registry get <name>` — Show full registry entry (pipe-delimited).
- `registry list [--status S] [--kind K] [--service S]` — List entries.
- `registry update <name> [--description D] [--severity L] [--status S]` — Update fields.
- `registry deprecate <name>` — Set status to `deprecated`.
- `registry count [--status S]` — Count entries.
- `registry discover` — Discover `emit-event.sh` call sites across three runtime surfaces (YOK-1240): shell scripts in `scripts/`, SKILL `.md` files in `skills/`, and Python files in `runtime/api/`. Also detects special emitter patterns (observe-tool.sh Python-embedded emitters, deploy-pipeline.sh variable-based emitters). Excludes test directories and prose-only matches.
- `registry audit` — Combined registry health report (stale entries, rogue events, unregistered call sites, deprecated with active call sites).
- `registry diff [--verbose]` — Registry vs codebase diff. Only reports drift for active registry entries; deprecated entries without call sites are expected and shown only in `--verbose` mode (prefixed with `~`).

Key behavior:
- Three-tier DB path resolution via `resolve-paths.sh`
- WAL mode for concurrent read/write safety
- 5-second busy timeout for DB contention during parallel dispatch
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

### emit-event.sh
**Input:** Named parameters (all `--flag value` style)
**Purpose:** Universal event emitter for the Yoke structured logging system. Accepts named parameters, builds the full JSON envelope, generates `event_id` (UUID) if not provided, resolves `session_id` via fallback chain, checks write-side severity config, enforces envelope size limits, and inserts via `yoke-db.sh events insert`. POSIX sh.

Required flags:
- `--name "EventName"` — Event name (PascalCase, grep-discoverable)
- `--kind <kind>` — Event kind enum: `analytics`, `system`, `audit`, `security`, `metric`
- `--type <type>` — Event type (free string, project-specific)
- `--source-type <source>` — Source type: `agent`, `backend`, `frontend`, `system`

Optional flags:
- `--session-id`, `--event-id`, `--severity`, `--outcome`, `--agent`, `--tool-name`, `--duration-ms`, `--exit-code`, `--item-id`, `--task-num`, `--project`, `--service`, `--environment`, `--org-id`, `--actor`, `--trace-id`, `--parent-id`, `--anomaly-flags`, `--context` (JSON), `--error-context` (JSON)

Session ID fallback chain (cross-harness, YOK-1271):
1. `--session-id` parameter (explicit)
2. `$YOKE_SESSION_ID` environment variable
3. `$CLAUDE_SESSION_ID` (Claude Code runtime)
4. `$CODEX_THREAD_ID` (Codex runtime)
5. `$(date +%s)-$$` fallback (timestamp-PID)

Size limits (NFR-8):
- Total envelope: 64KB (65536 bytes)
- Context field: 2KB (2048 bytes)
- Stacktrace (in error-context): 4KB (4096 bytes)

Test mode (`YOKE_EVENTS_CAPTURE`):
- When `YOKE_EVENTS_CAPTURE=1` and `YOKE_EVENTS_FILE` is set, writes JSON envelopes as NDJSON to the capture file instead of DB insertion.
- Enables assertion-based testing via `test-events-helpers.sh`.

Key behavior:
- UUID generation: prefers `uuidgen`, falls back to `python3`, last resort timestamp+PID
- When `--project` is omitted but `--item-id` resolves to an item row, infers `project` from `items.project` before falling back to `yoke`
- Write-side severity check against `severity_config` table before inserting
- Error category validation: `agent_failure`, `hook_failure`, `db`, `git`, `dispatch`, `verification`, `external`, `unknown`
- Exit codes: 0 = success (or silently dropped by severity filter), 1 = error, 2 = usage error

### repair-status-events.py
*Repair / one-time script.*
**Input:** `[--db PATH] [--dry-run]`
**Purpose:** Repairs lifecycle delivery telemetry for board meters. Fixes misattributed `ItemStatusChanged` / `TaskStatusChanged` rows by syncing `events.project` to `items.project`, backfills missing success events for item success states (`implemented` / `done`) from `items.merged_at` or `items.updated_at`, and backfills missing epic-task success events for `reviewed-implementation` / `done` from the parent epic completion timestamp when no task event exists.

### test-events-helpers.sh
**Input:** Library — source this file after `test-helpers.sh`; do not execute directly.
**Purpose:** Test harness for `YOKE_EVENTS_CAPTURE` mode. Provides capture/assert functions for testing event emission without DB side effects. Used by event integration tests.

Functions:
- `events_capture_start` — Set up capture mode (exports `YOKE_EVENTS_CAPTURE=1`, creates temp file)
- `events_capture_stop` — Unset capture mode env vars
- `events_capture_reset` — Clear captured events (truncate file)
- `events_capture_count` — Print number of captured events
- `events_capture_get N` — Print Nth captured event JSON (1-based)
- `events_capture_get_field N FIELD` — Print field value from Nth event
- `assert_event_count LABEL EXPECTED` — Assert exact event count
- `assert_event_name LABEL N NAME` — Assert Nth event has given name
- `assert_event_field LABEL N FIELD VALUE` — Assert field equals value
- `assert_event_field_not_empty LABEL N FIELD` — Assert field is non-empty
- `assert_event_field_contains LABEL N FIELD PATTERN` — Assert field contains pattern
- `assert_no_event_named LABEL NAME` — Assert no event with given name exists

### lint-event-registry.sh
**Input:** JSON on stdin (PreToolUse hook payload)
**Purpose:** PreToolUse hook for event registry enforcement. Intercepts Bash commands containing `emit-event.sh` and validates the `--name` argument against the `event_registry` table. POSIX sh.

Three outcomes:
- **Registered (active):** exit 0 (allow, no output)
- **Registered (deprecated):** exit 0 (allow), warning to stderr suggesting deprecation
- **Not registered:** deny JSON to stdout with `permissionDecision: "deny"` and a message including the `registry add` command to register the event

Graceful degradation:
- If `event_registry` table does not exist, exit 0 (allow all)
- If `yoke.db` is not found, exit 0 (allow all)

Scope limitation: only validates direct `emit-event.sh` calls in Bash commands. Indirect invocations (e.g., `emit-event.sh` called from within another script) are not intercepted by this hook.

## Track & Epic Scripts

### yoke-db.sh epic *(thin launcher → Python domain module)*
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh epic <subcommand>`
**Purpose:** Thin launcher delegating to `runtime.api.domain.epic` (YOK-1246 task 006). All domain logic (task CRUD, progress notes, reviews, dispatch chains, file tracking) lives in the Python module. This file exists solely to preserve the `sh "$SCRIPT_DIR/yoke-db.sh" epic` calling convention. Manages `epic_tasks`, `epic_task_files`, `epic_dispatch_chains`, and `epic_progress_notes` tables.

Subcommands:
- `task-upsert <epic_id> <task_num> <title> <worktree> <context_estimate> <dependencies>` — Insert or replace an epic task row (uses Python parameterized query for title safety)
- `task-get <epic_id> <task_num>` — Get one task row (pipe-delimited: id|epic_id|task_num|title|worktree|context_estimate|dependencies|status|dispatch_attempts)
- `task-list <epic_id>` — List all tasks for an epic (ordered by task_num ASC)
- `task-update-status <epic_id> <task_num> <status>` — Update the status field of a task
- `file-add <epic_id> <task_num> <file_path> <action>` — Add a file entry for a task
- `file-list <epic_id> <task_num>` — List all files for a task (pipe-delimited: id|epic_id|task_num|file_path|action)

Key behavior:
- Worktree-aware DB path resolution accepts either repo-root or concrete `yoke/` values for `$YOKE_ROOT`, normalizes through the canonical resolver, then falls back to `$CLAUDE_PROJECT_DIR/yoke` or git root with `.worktrees/` stripping
- WAL mode for concurrency safety
- Uses Python parameterized queries for `task-upsert` (body-safe multi-line content)
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

## Deployment Scripts

### flow-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh flows <subcommand>`
**Purpose:** SQLite CRUD wrapper for the `deployment_flows` table. Manages deployment flow definitions with JSON stage pipeline validation. POSIX sh, uses `sqlite3` and `python3` (for stage validation).

Subcommands:
- `init` — Create `deployment_flows` table + seed 5 flows (idempotent). Also adds `deployment_flow` and `deploy_stage` columns to the `items` table.
- `create <id> <project> <name> <description> <stages_json> [on_failure]` — Insert a new deployment flow. Validates that stages is a JSON array where each element has `name` and `executor` fields, and executor is in the closed set of valid types.
- `get <id> [field]` — Get flow as pipe-delimited row or single field value. Valid fields: `id`, `project`, `name`, `description`, `stages`, `on_failure`, `created_at`.
- `list [--project <project>]` — List flows as pipe-delimited rows, optionally filtered by project.
- `stages <id>` — Output raw JSON stages array for a flow.

Valid executor types: `auto`, `deploy-command`, `health-check`, `test-suite`, `adaptive-e2e`, `ephemeral-deploy`, `ephemeral-teardown`, `human-approval`, `script`, `github-actions-workflow`.

Key behavior:
- Three-tier DB path resolution via `resolve-paths.sh`
- WAL mode for concurrency safety
- Stage validation via Python3 (checks JSON structure, required fields, executor closed set)
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

### yoke-db.sh runs *(thin launcher → Python domain module)*
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh runs <subcommand>`
**Purpose:** Thin launcher delegating to `runtime.api.domain.deployment_runs` (YOK-1246 task 003). All domain logic (run lifecycle, item membership, QA requirements, preview environments, composition validation) lives in the Python module. This file exists solely to preserve the `sh "$SCRIPT_DIR/yoke-db.sh" runs` calling convention. Manages `deployment_runs`, `deployment_run_items`, `deployment_run_qa`, and `deployment_preview_environments` tables.

Subcommands:
- `init` — Create tables if not exist (idempotent).
- `create-run <project> <flow> [--target-env X] [--release-lineage Y] [--created-by Z]` — Generate next run ID, insert, print ID.
- `add-item <run-id> <item-id>` — Add item to run.
- `remove-item <run-id> <item-id>` — Remove item from run.
- `get <run-id> [field]` — Get run (pipe-delimited row or single field).
- `update <run-id> <field> <value>` — Update run column; auto-set timestamps.
- `list [--project X] [--status Y]` — List runs (pipe-delimited).
- `items <run-id>` — List items in a run (pipe-delimited).
- `lineage <run-id>` — Return all runs sharing same release_lineage.
- `lineage-create` — Generate a new lineage ID.
- `lineage-final-status <lineage-id>` — Status of last production-target run in lineage.
- `next-id` — Generate next run ID for today.
- `qa-add <run-id> <check-name> <source> <blocking>` — Add QA requirement to run.
- `qa-list <run-id>` — List QA requirements for a run.
- `qa-update <run-id> <check-name> <status>` — Update QA check status.
- `validate-composition <run-id>` — Check project match, flow, status, deps.
- `check-batch-compatibility <project> <flow> <item-id> [...]` — Validate proposed items before run creation.
- `preview-check <project> <env-name>` — Return occupancy status of preview env.
- `preview-claim <run-id> <project> <env-name>` — Claim preview environment for run.
- `preview-release <run-id>` — Release preview environment after run.
- `check-preview-occupancy <project> <env-name>` — Structured occupancy: empty, active, or stale.
- `claim-preview <run-id> <project> <env-name> [--env-type shared|adhoc]` — Claim preview and emit event.
- `can-cleanup-preview <run-id>` — Exit 0 if cleanup allowed, 1 if blocked.
- `resolve-target-env <project> <flow> [--target-env override]` — Resolve target env from flow default or override.

Key behavior:
- Three-tier DB path resolution via `resolve-paths.sh`
- WAL mode for concurrency safety
- Human-readable run IDs: `run-YYYYMMDD-NNN` (e.g., `run-20260315-001`)
- All run lifecycle transitions emit events via `emit-event.sh`
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

### env-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh envs <subcommand>`
**Purpose:** SQLite CRUD wrapper for the `ephemeral_environments` table. Manages per-branch ephemeral environment lifecycle for pre-merge E2E validation. Table is created by `project-db.sh init`. POSIX sh, uses `sqlite3`.

Subcommands:
- `create <project> <branch> [--item X] [--workflow-run-id Y] [--github-ref Z]` — Insert a new environment with `status=pending`, prints row ID. Uses INSERT OR REPLACE on UNIQUE(project, branch) to handle stale rows. Transitions to `starting` when a workflow run is found.
- `update <id> <field> <value>` — Update a field on an existing environment. Auto-sets `stopped_at` when status changes to `stopped` or `failed`. Valid update fields: status, branch, item, workflow_run_id, github_ref, port_api, port_web, url, started_at, stopped_at, health_check_url.
- `get <project> <branch>` — Get environment by project+branch (pipe-delimited).
- `get-by-id <id> [field]` — Get environment by ID (full pipe-delimited row or single field value).
- `list [--project X] [--status Y]` — List environments (pipe-delimited), optionally filtered by project and/or status.
- `cleanup [--max-age-hours N]` — Mark environments older than N hours (default: 24) as stopped, prints count of affected rows.

Key behavior:
- Three-tier DB path resolution via `resolve-paths.sh`
- WAL mode for concurrency safety
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

### harness-sessions-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh harness-sessions <subcommand>`
**Purpose:** SQLite CRUD wrapper for the `harness_sessions` and `work_claims` tables. Manages session lifecycle (`begin`, `touch`, `end`) and work-unit ownership (claim, release, query). Parallel consumer alongside the API endpoints in `runtime/api/main.py`. POSIX sh, uses `sqlite3`.

Subcommands -- session lifecycle:
- `begin <session-id> <executor> <provider> <model> <workspace> [lane] [mode]` -- Register a new session with identity fields. Sets `offered_at` and initial `last_heartbeat`.
- `touch <session-id> [--mode M]` -- Heartbeat an active session (updates `last_heartbeat`). Optionally updates the session mode (charge, feed, strategize, wait).
- `end <session-id> [--force]` -- End a session and set `ended_at`. The `--force` flag bypasses the chain-pending guard but does NOT bypass the active-claim guard (YOK-1388). Sessions with unreleased claims are protected from termination. Claims are released through the claim lifecycle or stale-session reclamation. For stranded claims, use `python3 -m runtime.api.service_client claim-release`.
- `get <session-id>` -- Get session details (pipe-delimited).
- `list` -- List active sessions (pipe-delimited).
- `stale [threshold-minutes]` -- List sessions whose `last_heartbeat` exceeds the staleness threshold.
- `reclaim <session-id>` -- Reclaim a stale session (ends it and releases all claims).

Subcommands -- work claims (YOK-1315: item-level only):
- `claim <session-id> <item-id>` -- Claim an item for a session (exclusive). Fails if already claimed by another active session. Epic task ownership uses the parent item claim.
- `release <claim-id> [reason]` -- Release a specific claim by ID.
- `release-all <session-id> [reason]` -- Release all active claims for a session.
- `list-claims <session-id>` -- List active claims for a session (pipe-delimited).
- `who-claims <item-id>` -- Query which session holds the claim on an item.

Key behavior:
- Three-tier DB path resolution via `resolve-paths.sh`
- WAL mode with busy timeout for concurrency safety
- Exclusive claims: only one active session can claim a given work unit at a time
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

### render-project.sh
**Input:** `<project> [--write] [--only DEPLOY.md|workflows|scaffold|all]`
**Location:** `yoke/templates/webapp/ops/render-project.sh` (not in scripts dir)
**Purpose:** Generate all ops artifacts for a project from templates. Reads templates from `yoke/templates/webapp/ops/` and `yoke/templates/webapp/scaffold/`, pulls project-specific values from DB (`project_capabilities`), `cdk.context.json`, and project config file, then renders filled artifacts to `yoke/projects/<project>/`.

Key behavior:
- **Without `--write`:** Prints rendered output to stdout (DEPLOY.md only in stdout mode).
- **With `--write`:** Saves all artifacts to their output locations.
- **`--only` filter:** `DEPLOY.md` (runbook only), `workflows` (GitHub Actions workflows only), `scaffold` (Docker/app scaffold files only), `all` (default -- everything).
- **Workflow rendering:** Renders `deploy.yml`, `hotfix.yml`, `smoke.yml`, `ephemeral-deploy.yml`, `ephemeral-teardown.yml` to `projects/{project}/workflows/{project}-{name}.yml`. Each rendered file gets an auto-generated header with source template path and regeneration command.
- **Scaffold rendering:** Renders `docker-compose.yml`, `app/Dockerfile`, `app/entrypoint.sh`, `app/web/Dockerfile`, `app/web/next.config.ts` to `projects/{project}/scaffold/` mirroring the template structure. Scaffold files get comment headers (shell-style `#` or JS-style `//` depending on file type).
- **Hotfix template:** `hotfix.yml` is identical to `deploy.yml` except: trigger is `workflow_dispatch` only (no `push: [main]`), name is `{{project_display_name}} Hotfix`. Rendered as `{project}-hotfix.yml`.
- **ssh_user handling:** Workflow templates use `${{ secrets.{{PROJECT_NAME_UPPER}}_SSH_USER }}` where only `{{PROJECT_NAME_UPPER}}` is a Yoke placeholder. Rendered output is `${{ secrets.BUZZ_SSH_USER }}` (secret reference, not hardcoded value).
- **Placeholder engine:** sed-based `{{placeholder}}` substitution. All new placeholders must be added to the `_render_file()` function's sed chain.
- Exit codes: 0 = success, 1 = error

### bootstrap-project.sh
**Input:** `[--preflight-only]`
**Purpose:** One-time Buzz GitHub Actions setup script. Wires Buzz into Yoke's GitHub Actions deployment pipeline.

Key behavior:
- **Preflight phase:** Historical script-era preflight for Buzz pipeline setup. This archive is not the live GitHub auth contract; current project auth resolves a verified repository binding and a short-lived GitHub App installation token, never `capability_secrets`.
- **Setup phase:** Creates GitHub Secrets (`BUZZ_SSH_KEY`, `BUZZ_SSH_HOST`, `BUZZ_SSH_USER`), creates `production` environment with required reviewer protection, generates and commits workflow files (`buzz-deploy.yml`, `buzz-ephemeral.yml`, `buzz-ephemeral-teardown.yml`, `buzz-smoke.yml`) to Buzz main, then verifies all resources.
- **How to run:** `sh .agents/skills/yoke/scripts/bootstrap-project.sh` (or `--preflight-only` for dry-run validation)
- **On failure:** Follow the preflight output instructions, then re-run the script.
- **Idempotent:** Safe to re-run. Secrets overwrite in place, environment updates, workflow files only committed if changed.
- **Env vars:** `BUZZ_SSH_KEY_PATH` overrides default SSH key location (`~/.ssh/id_rsa`)
- Exit codes: 0 = success, 1 = preflight failure (instructions printed), 2 = setup failure

### github-actions.sh
**Input:** `<subcommand> [args]`
**Purpose:** GitHub Actions integration script for triggering, polling, and finding workflow runs via `gh api`. Used by the `github-actions-workflow` executor type in the Usher pipeline. POSIX sh, uses `gh` CLI and `python3` (JSON parsing).

Subcommands:
- `trigger <repo> <workflow> [--ref <branch>]` — Dispatch workflow via `gh api`, wait briefly for run to appear, print run ID. Repo is a GitHub slug (e.g., `example-org/buzz`). Default ref: `main`.
- `poll <repo> <run-id>` — Get run status. Prints `success`, `failed:{conclusion}`, `waiting`, `in_progress`, or `unknown:{status}`.
- `find-run <repo> <workflow> <commit-sha>` — Find run by commit SHA. Prints run ID if found, `not_found` otherwise.

Key behavior:
- **Auth check:** Historical script-era readiness check. Current callers use the project GitHub auth resolver.
- **Repository access:** Project GitHub App auth that can dispatch workflows and read run status.
- **JSON parsing:** Uses `python3` for JSON field extraction from `gh api` responses
- Exit codes: 0 = success, 1 = failed/not found, 2 = waiting (poll only), 3 = in-progress (poll only), 4 = project auth failure

### deploy-pipeline.sh
**Input:** `<run-id|item-id> [--timeout <minutes>] [--from-stage <stage>] [--fresh]`
**Purpose:** Deployment pipeline orchestrator. Accepts a deployment run ID or item ID, iterates through stages, and dispatches the correct executor for each stage type. Called by the Usher skill (`/yoke usher YOK-N`). POSIX sh, uses `python3` (stage parsing).

Key behavior:
- When first argument matches `run-*`, treated as a deployment run ID; otherwise as item ID (auto-creates a single-item run)
- `--fresh` flag creates a new run even if an existing run exists for the item
- Reads stage definitions from `deployment_flows` via `flow-db.sh stages`
- Resumes from current `current_stage` on the run (strips `-failed` suffix for retry)
- Already-succeeded runs exit 0 immediately (no-op)
- For `github-actions-workflow` stages: resolves `github_repo` from `projects` table, triggers workflow, polls with timeout
- Dispatches executors from `scripts/executors/` directory
- Updates `current_stage` on the `deployment_runs` row after each stage
- Emits deployment run events to the unified `events` table via `emit-event.sh`
- Stage authority lives on the run, not on individual items
- Exit codes: 0 = pipeline complete, 1 = stage failed, 2 = awaiting human approval, 3 = usage/setup error

### deploy-qa-recorder.sh
**Input:** `<subcommand> <run-id> [args]`
**Purpose:** Generic deployment QA recording for pipeline stages. Bridges `deploy-pipeline.sh` stage results into `qa_requirements`, `qa_runs`, `qa_artifacts`, and `deployment_run_qa` tables.

Subcommands:
- `seed-from-flow <run-id>` — Scan flow stages and seed QA requirements for QA-relevant stages (those with `qa_kind` in config or "smoke" in name). Idempotent.
- `record-stage-result <run-id> <stage-name> <verdict> [--raw-result <json>] [--duration-ms <ms>]` — Record a `qa_run`, attach log artifact, update `deployment_run_qa` status.

### backfill-deployment-flows.sh
*Migration / one-time script.*
**Input:** `[--dry-run]`
**Purpose:** One-time migration to assign `deployment_flow` to existing items missing one (YOK-853). Rules: yoke items get `yoke-internal`; external project items get the project's `default_deployment_flow`. Items already having a flow are not touched. Only non-terminal, non-epic items are backfilled.

### Executor Scripts (scripts/executors/)
**Purpose:** Stage executor scripts dispatched by `deploy-pipeline.sh`. Each handles one executor type. All POSIX sh.

Scripts:
- `exec-auto.sh` — No-op executor for stages requiring no action (e.g., "start", "complete"). Prints log message, exits 0.
- `exec-health-check.sh <url>` — HTTP health check via `curl -sf`. Exits 0 on 2xx response, 1 on failure.
- `exec-script.sh <command>` — Shell command executor via `sh -c`. Passes through the command's exit code directly.

## Backup Scripts

> **Retired (YOK-1364 / YOK-1252):** The shell entrypoints documented below have
> been replaced by the Python owner `runtime.api.domain.backup`. All current
> callers — including `GovernedMigration` (YOK-1255), `events_crud.cmd_prune`,
> the envelope repair helper, and operator invocations — go through
> `python3 -m runtime.api.domain.backup {backup|list|latest|prune}`.  The
> `backup-db.sh` text below is retained as historical context for the
> pre-zero-shell contract and the original YOK-957 / YOK-958 behaviors only.

### backup-db.sh
**Input:** `<mode> [options]`
**Purpose:** SQLite-safe local backup helper for `yoke.db` (YOK-957, YOK-958). Creates timestamped, reason-tagged backups using `sqlite3 .backup` (WAL-safe). Enforces a retention cap by deleting oldest backups after successful creation. Backups live in `yoke/backups/` which is gitignored — they are never committed to source control. Optionally uploads backups to S3 if a `db-backup-s3` capability is configured for the project (YOK-958).

Modes:
- `backup <reason>` or `backup --reason <reason>` — Create a backup with the given reason slug (e.g., `pre-migration`, `pre-recovery`, `periodic`). Input is sanitized: spaces, colons, and path separators become hyphens; quotes and other invalid characters are stripped; repeated separators are collapsed. Final slug must match `[A-Za-z0-9_.-]`. If sanitization produces an empty slug, an error is shown with the allowed format and a working example.
- `periodic` — Create a backup only if the newest existing backup is older than the configured staleness window (default: 24 hours, configurable via `backup_staleness_hours` in `yoke/config`).
- `prune` — Run retention pruning without creating a new backup.
- `list` — List existing backups (newest first).
- `latest` — Print path to most recent backup (empty if none).

Options:
- `--max-count N` — Override retention cap (default: `backup_max_count` config key, or 20).
- `--staleness-hours N` — Override staleness window for periodic mode (default: `backup_staleness_hours` config key, or 24).
- `--db PATH` — Override DB path (default: `resolve-paths.sh db`).
- `--backup-dir PATH` — Override backup directory (default: `yoke/backups/`).
- `--no-s3` — Skip S3 upload even if `db-backup-s3` capability is configured.
- `--project PROJECT` — Project ID for capability lookup (default: `yoke`).

Filename pattern: `yoke.db.YYYYmmdd-HHMMSS.<reason>.sqlite3`

**Hard-block behavior:** All destructive migration scripts call `backup-db.sh backup pre-migration` before modifying live tables. If the backup fails, the migration exits nonzero without proceeding. Recovery scripts use `backup pre-recovery`. **Current owner:** `GovernedMigration` (YOK-1255) invokes `runtime.api.domain.backup` via Python; YOK-1252 audit-fingerprint exceptions reference the same owner. See `yoke/docs/events-incident-followup.md` §1 for the per-path safety inventory.

**S3 upload behavior (YOK-958):** If a `db-backup-s3` capability is configured for the project, local backups are uploaded to S3 after successful local creation. The `aws-admin` capability alone does NOT auto-enable cloud backup — `db-backup-s3` must be explicitly configured. Upload failure behavior depends on `required_upload`:
- `required_upload=false` (default): Upload failure emits a warning but `backup-db.sh` still exits 0 (local backup is sufficient).
- `required_upload=true`: Upload failure causes `backup-db.sh` to exit 1, blocking destructive operations.

Remote retention: If `retention_count_remote` is set, oldest remote backups beyond the count are pruned after each successful upload.

**Config keys:** `backup_max_count` (retention cap, default 20), `backup_staleness_hours` (periodic staleness threshold, default 24).


## Migration Scripts

### migrate-to-sqlite.sh
**Deleted.** One-time migration from backlog `.md` files to SQLite. Completed and removed. See `runtime/api/tools/migrate_to_sqlite.py` for the Python successor (also completed).

### generate-backlog-md.sh
**Deleted (YOK-1383).** Backlog `.md` files are no longer generated. Item body content is a virtual rendered field read via `items get YOK-N body`.

### render-body.sh
**Superseded by `python3 -m runtime.api.domain.render_body` (YOK-1383).** Body rendering is now on-demand — `items get YOK-N body` calls `render_body.py` to assemble structured DB fields into markdown. No stored `body` column or `body_generated_at` timestamp.

Section ordering (deterministic):
1. `spec` (under `# Spec: {title}`)
2. `design_spec` (under `## Design Spec`)
3. `technical_plan` (under `## Technical Plan`)
4. `worktree_plan` (under `## Worktree Plan`)
5. `item_sections` with `ordering < 500`
6. `shepherd_caveats` (under `## Shepherd Caveats`)
7. Shepherd Log (via `shepherd-db.sh shepherd-log`)
8. `test_results` (under `## Test Results`)
9. `deploy_log` (under `## Deploy Log`)
10. `item_sections` with `ordering >= 500`

Key behavior:
- NULL/empty fields produce no section in output (no empty headings)
- Running twice with no intervening writes produces byte-identical output (idempotent)
- Items with all structured fields NULL and a non-empty body are left unchanged (backward compat)
- `--output-file <path>` writes markdown to file instead of updating DB
- Triggers GitHub sync via `sync-helper.sh`
- Accepts `YOK-` prefix on item IDs (e.g., `YOK-42` or `42`)
- Exit codes: 0 = success, 1 = error

## Shepherd Scripts

### shepherd-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh shepherd <subcommand>`
**Purpose:** SQLite CRUD wrapper for Shepherd tables. Manages tables: `shepherd_verdicts`, `caveat_dispositions`, `item_dependencies`. POSIX sh, uses `sqlite3` and `python3`.

Key subcommands:
- `init` — Create all tables (idempotent)
- `verdict <item> <transition> <worker> <verdict> [caveats] [session_id]` — Record a Boss verdict. Auto-increments attempt count per item+transition+worker.
- `shepherd-log <item_id>` — Render Shepherd Log as Markdown for an item. Queries `shepherd_verdicts` table, outputs chronologically-ordered sections with transition, worker, attempt, verdict, and caveats. Empty items get `<!-- No verdicts recorded -->` comment.
- `caveat-disposition <item> <transition> <attempt> <caveat_num> <caveat_text> <disposition> [resolution_details] [verdict_id]` — Record a caveat disposition (RESOLVED or DEFERRED)
- `caveat-dispositions <item>` — List all caveat dispositions for an item (pipe-delimited)
- `dependency-add <dependent> <blocking> <type> <source>` — Add a cross-item dependency edge
- `dependency-list <item>` — List dependencies in both directions (pipe-delimited)

Key behavior:
- Worktree-aware DB path resolution accepts either repo-root or concrete `yoke/` values for `$YOKE_ROOT`, normalizes through the canonical resolver, then falls back to `$CLAUDE_PROJECT_DIR/yoke` or git root with `.worktrees/` stripping
- `shepherd-log` handles multiline caveats via `%%NL%%` delimiter in SQL
- `verdict` auto-calculates attempt number via `MAX(attempt)` query
- Exit codes: 0 = success, 1 = error/not found

### release-notes-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh release <subcommand>`
**Purpose:** SQLite CRUD wrapper for the `release_entries` table. Stores per-item release note entries in `yoke/yoke.db`. The `release_entries` table is the canonical store — no rendered `.md` files. Supports per-project scoping via `--project` flag (YOK-573).

Subcommands:
- `insert <item_id> <category> <title> [version] [--project <name>]` -- Insert a release entry. Category must be: features, improvements, bug_fixes, internal. Version defaults to date. Project defaults to `items.project` for the given item_id, falling back to `yoke`.
- `exists <item_id> [version] [--project <name>]` -- Exit 0 if entry exists, 1 if not. When `--project` is provided, scopes the check to that project. Without it, matches any project.
- `list [version] [--project <name>]` -- List entries as pipe-delimited rows (item_id|category|title|version|project|created_at). When `--project` is provided, only entries for that project are returned.

Key behavior:
- `_current_version()` returns a UTC `YYYY-MM-DD` version string
- `_resolve_item_project()` resolves project from `items.project` column, falling back to `yoke`
- `INSERT OR REPLACE` handles idempotent re-inserts (UNIQUE constraint on item_id + version + project)
- Exit codes: 0 = success, 1 = error/not found

### yoke-db.sh qa *(thin launcher → Python domain module, YOK-833)*
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh qa <subcommand>`
**Purpose:** Thin launcher delegating to `runtime.api.domain.qa` (YOK-1246 task 005). All domain logic (QA requirements, runs, artifacts, verdicts, success policies) lives in the Python module. This file exists solely to preserve the `sh "$SCRIPT_DIR/yoke-db.sh" qa` calling convention. Manages `qa_requirements`, `qa_runs`, and `qa_artifacts` tables. Full documentation: `yoke/docs/qa-platform.md`.

Subcommands:
- `init` — Create QA tables and indexes (idempotent; also created by `schema-db.sh init`).
- `requirement-add [flags]` — Insert a `qa_requirement` row. Requires `--qa-kind` and `--qa-phase` plus exactly one of `--item-id`, `(--epic-id + --task-num)`, or `--deployment-run-id`. Optional: `--target-env`, `--blocking-mode`, `--requirement-source`, `--success-policy` (JSON), `--capability-requirements` (JSON), `--suite-id`. Prints inserted row ID.
- `requirement-list [filters]` — List requirements (pipe-delimited). Filters: `--item-id`, `--epic-id`, `--task-num`, `--deployment-run-id`, `--qa-phase`, `--blocking-mode`.
- `requirement-get <id>` — Get a single requirement (pipe-delimited).
- `requirement-waive <id> <rationale>` — Set `waived_at` and `waiver_rationale` on a requirement.
- `run-add [flags]` — Insert a `qa_run` row. Requires `--requirement-id`, `--executor-type`, `--qa-kind`. Optional: `--verdict`, `--score`, `--confidence`, `--raw-result` (JSON), `--duration-ms`, `--started-at`, `--completed-at`. Prints inserted row ID.
- `run-list [filters]` — List runs (pipe-delimited). Filters: `--requirement-id`, `--qa-kind`, `--verdict`.
- `run-get <id>` — Get a single run (pipe-delimited).
- `artifact-add [flags]` — Insert a `qa_artifact` row. Requires `--run-id`, `--artifact-type`. Optional: `--content-type`, `--storage-path`, `--metadata` (JSON). Prints inserted row ID.
- `artifact-list [filters]` — List artifacts (pipe-delimited). Filters: `--run-id`, `--artifact-type`.

Key behavior:
- Busy timeout: 5000ms for all sqlite3 calls
- WAL journal mode enabled
- DB path resolved via `resolve-paths.sh yoke-root`
- Polymorphic FK constraint on `qa_requirements` enforces exactly one attachment target
- Exit codes: 0 = success, 1 = error/not found, 2 = usage error

### qa-gate-check.sh (YOK-833)
**Input:** Sourced library (`. "$SCRIPT_DIR/qa-gate-check.sh"`)
**Purpose:** Provides reusable QA gating functions called by `backlog-registry.sh` and the Python epic domain module (`runtime.api.domain.epic`) during item/task status transitions.

Functions:
- `check_verification_entry <target>` — Returns 0 if at least one `qa_requirements` row exists for the target, 1 if not. Prints error on failure.
- `check_reviewed_implementation_gate <target>` — Returns 0 if all blocking `verification`-phase requirements needed for the `reviewed-implementation` handoff are satisfied or waived. Returns 1 if any are unsatisfied.
- `check_done_gate <target>` — Returns 0 if all blocking requirements across all phases are satisfied. Returns 1 if any are unsatisfied.
- `check_epic_simulation_gate <epic_item_id>` — Authoritative integration simulation gate for epic items (YOK-1203). Returns 0 if the latest canonical simulation is CLEAN or GAPS FOUND (non-critical). Returns 1 if missing, inconclusive, or has blocking gaps (CRITICAL severity or BLOCK/REQUIRED recommendation). Used by both the conduct reviewed-handoff path and `done-transition.sh` to ensure consistent epic progression semantics.

Argument format: plain integer for items (e.g., `42`), `epic_id:task_num` for epic tasks (e.g., `833:5`). `check_epic_simulation_gate` takes a plain integer only.

Environment:
- `YOKE_DB` — path to yoke.db (required)
- `YOKE_QA_GATE_BYPASS` — set to `1` to bypass all gates
- `YOKE_SKIP_SIMULATION` — set to `1` to bypass the epic simulation gate only

### designs-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh designs <subcommand>`
**Purpose:** SQLite CRUD wrapper for the `designs` table. Manages design documents (UX specs) linked to backlog items. One design per item (UNIQUE constraint on `item_id`). Body inserts use Python3 for safe parameterized SQL. The `.md` files in `yoke/designs/` are generated views from the DB — write to the DB, then sync to regenerate files.

Subcommands:
- `init` — Ensure `designs` table and indexes exist (idempotent).
- `upsert <item_id> <slug> --body-file <path>` — Insert or update a design. Strips `YOK-` prefix from item_id. Body read from file via Python parameterized query.
- `get <item_id>` — Get design for an item (pipe-delimited: `id|item_id|slug|body|created_at|updated_at`). Exit 1 if not found.
- `exists <item_id>` — Check if design exists. Prints `true`/`false` to stdout. Exit 0 if exists, exit 1 if not.
- `list` — List all designs (pipe-delimited: `id|item_id|slug|created_at|updated_at`), ordered by `item_id ASC`.
- `sync <item_id>` — Write design body to `yoke/designs/<slug>.md`. Creates the directory if needed.
- `sync-all` — Write all designs to `yoke/designs/`. Creates the directory if needed.
- `migrate-legacy [--delete-files]` — Ingest 3 hardcoded legacy `.md` files from `yoke/designs/` into the DB. Mapping: `project-awareness.md` -> item 51, `cicd-environment-progression.md` -> item 126, `PAD-migration-sprint.md` -> item 278. Idempotent (skips already-migrated). `--delete-files` removes originals after migration.

Key behavior:
- Auto-initializes the `designs` table via `cmd_init` on every subcommand that needs it
- Busy timeout: 5000ms for all sqlite3 calls
- WAL journal mode for Python-based operations
- DB path resolved via `resolve-paths.sh yoke-root`

### project-db.sh
**Input:** `<subcommand> [args]`
**Also accessible via:** `yoke-db.sh projects <subcommand>`
**Purpose:** SQLite CRUD wrapper for the project domain tables (`projects`, `sites`, `environments`, `project_capabilities`, `capability_templates`). Manages multi-project configuration including repo paths, context files for agent prompt injection, and test commands. Seeds Yoke and Buzz project data on init.

Subcommands:
- `init` — Create all 5 tables and seed Yoke/Buzz data (idempotent via INSERT OR IGNORE). Seeds capability templates (ssh, docker, ephemeral-env, aws-admin, aws-route53), Buzz sites, environments, and project capabilities.
- `create <id> <name> <repo_path>` — Insert a new project record.
- `get <id> [field]` — Get full project row (pipe-delimited) or a single field value.
- `list` — List all projects (pipe-delimited).
- `update <id> <field> <value>` — Update a single field on a project.
- `has-capability <project> <type>` — Exit 0 if capability exists, 1 if not.
- Capability settings/secrets commands — manage non-sensitive settings and credentials separately.
- `capability-list <project>` — List all capabilities for a project.
- `capability-get-settings <project> <type>` — Get non-sensitive `settings` JSON.
- `capability-set-settings <project> <type> <settings-json>` — Update `settings` JSON.
- `capability-get-secret <project> <type> <key>` — Resolve a secret value.
- `capability-set-secret <project> <type> <key> <value>` — Set a secret value.
- `capability-list-secrets <project>` — List all capability types with secrets.
- `resolve-deploy-envs <project-id>` — (YOK-1131, YOK-1154) Returns distinct valid deployment environments for a project. Sources: DB `environments` (via `sites`) UNION `deployment_flows.target_env` UNION `project_capabilities` deployment_environments config. No config-file fallback — DB is the sole source of truth. Exit 0 if environments found, 1 if none. Output: newline-separated environment names, sorted. Used by `doctor.sh` (HC-undeployed-done).

Key behavior:
- Auto-initializes tables via `cmd_init` on every subcommand
- Busy timeout: 5000ms for all sqlite3 calls
- DB path resolved via `resolve-paths.sh yoke-root`
- Capability config has two JSON columns: `config` (may contain secrets, gitignored), `settings` (non-sensitive, safe to log)

## Lifecycle & Vocabulary Registries

### status-lifecycle.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** Generated compatibility adapter over `runtime/api/domain/lifecycle.py` (YOK-828, YOK-1113). Provides shell-callable constants and helpers for delivery item and epic task status constants, canonical progression order, board display order, terminal state checks, and SQL fragment generation. The Python module is the canonical source of truth.

Key constants/functions:
- `ITEM_STATUSES` — all valid item statuses (space-separated)
- `EPIC_TASK_STATUSES` — all valid epic task statuses
- `CANONICAL_PROGRESSION` — ordered issue progression: `idea refining-idea refined-idea implementing reviewing-implementation reviewed-implementation polishing-implementation implemented release done` (epics insert `planning plan-drafted refining-plan planned` before `implementing`)
- `BOARD_DISPLAY_ORDER` — status order for board rendering
- `EXCEPTIONAL_STATUSES` — `blocked stopped failed cancelled`
- `is_terminal_status <status>` — returns 0 if done/cancelled/failed
- `is_exceptional_status <status>` — returns 0 if blocked/stopped/failed/cancelled
- `status_sql_in <var-name>` — generates SQL IN clause from status list

Scope: defines the lifecycle for the SOFTWARE DELIVERY workflow family only. Shared control-plane semantics (approvals, halts) live in `approval-vocabulary.sh`.

### approval-vocabulary.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** Generated compatibility adapter over `runtime/api/domain/approval.py` (YOK-1113). Provides shell-callable constants for approval halt states, approval actions, stage authority ownership, and the distinction between Yoke-handled and external approval paths. The Python module is the canonical source of truth. Applies across all workflow families.

## Classification & Validation Helpers

### classify-browser-qa.sh
**Input:** `<item-id>` or `--project <project> --title <title> --acs <acs-text> [--flow <flow>]`
**Purpose:** Classify whether a backlog item is browser-testable (YOK-834). Uses conservative heuristics to determine if an item needs browser QA and whether it has visual outcomes.

Output (one line per key):
- `browser_testable=true|false`
- `visual_outcome=true|false`
- `route_hints=/login,/forgot-password` (comma-separated, deduplicated)
- `route_hint=/login` (first route, backward compat)

Classification heuristics:
1. Project capability: project has `browser-qa` capability → `true`
2. Deployment flow: flow contains web/browser/frontend keywords → `true`
3. Title/AC text: keyword scan for browser-related terms → `true`
4. Visual outcome: subset of browser keywords indicating UI changes → `true`

Exit codes: 0 = success, 1 = error, 2 = usage error

### classify-dirty-files.sh
**Input:** Sourced library (`. "$SCRIPT_DIR/classify-dirty-files.sh"`)
**Purpose:** Single source of truth for classifying dirty files as Yoke-managed or user-authored (YOK-501). Sourced by `done-transition.sh` and `merge-worktree.sh`.

Key functions:
- `classify_file(file)` — Prints `"yoke-managed"` or `"user-authored"`.
- `classify_dirty_files([exclude_worktrees])` — Classifies all dirty files (tracked + staged + untracked). Sets `_CDF_YOKE_FILES` and `_CDF_USER_FILES` (space-separated lists). Pass `1` to exclude `.worktrees/` and `.claude/worktrees/` paths.
- `is_yoke_managed_backlog(file)` — Two-tier body-diff classification for backlog items. Extracts the body (everything after the second `---` delimiter) from both the working copy and `git show HEAD:{file}`. Returns 0 if bodies are identical (frontmatter-only change). Returns 1 if bodies differ or file is untracked (safe default). Uses PID-suffixed temp files in `/tmp`.
- `is_yoke_managed_pattern(file)` — Pattern-only classification (no body-diff). Returns 0 if the file matches any `YOKE_MANAGED_PATTERNS` glob. Used by preflight checks where body-diff is not needed.

Key variables:
- `YOKE_MANAGED_PATTERNS` — Space-separated glob patterns for Yoke-managed files. Adding a new Yoke-managed path requires editing only this variable.

Technical notes:
- Uses `set -f` / `set +f` to prevent shell glob expansion when iterating patterns.
- Internal variables use `_cdf_` prefix to avoid collisions with callers.
- POSIX sh compliant (`local` is the only deviation).

## Browser Scripts

### browser-daemon.sh
**Thin launcher** → `python3 -m runtime.api.domain.browser_client daemon` (YOK-1340)

Lifecycle management for the Playwright browser daemon. All semantics (state file reading, HTTP client, start/stop/status/health, npm/Chromium auto-bootstrap) live in `runtime.api.domain.browser_client`.

- Exit codes: 0=success, 1=failed, 2=daemon not running, 3=usage error

### browser-snapshot.sh
**Thin launcher** → `python3 -m runtime.api.domain.browser_client snapshot` (YOK-1340)

Snapshot primitives: accessibility trees, screenshots, pixel-level diffs. All semantics live in `runtime.api.domain.browser_client`.

- Exit codes: 0=success, 1=failed, 2=daemon not running, 3=usage error

### browser-exec.sh
**Thin launcher** → `python3 -m runtime.api.domain.browser_client exec` (YOK-1340)

Step execution against the browser daemon. All semantics live in `runtime.api.domain.browser_client`.

- Exit codes: 0=success, 1=failed, 2=daemon not running, 3=usage error

### browser-run-scenario.sh
**Input:** `--item-id N --project P [--base-url URL]`
**Purpose:** Canonical orchestrator for browser QA scenario execution (YOK-946). Queries `qa_requirements` for an item's `browser_smoke` and `browser_diff` requirements, executes their scenario steps sequentially via `browser-exec.sh step`, and records `qa_runs` and `qa_artifacts`.

Key behavior:
- Single entry point for all browser QA execution -- used by both direct advance and conduct Tester paths
- Resolves `base_url` from CLI flag or `success_policy.base_url`
- Validates URL reachability (DNS + HTTP probe) before executing
- Auto-starts browser daemon if not running
- Creates one `qa_run` per requirement with `executor_type='browser_substrate'`
- Records `qa_artifact` entries for screenshots; artifact recording failures fail the run
- Outputs JSON summary on stdout: `{"verdict":"pass|fail","runs":[...]}`
- Re-entrant: retrying after failure creates new runs alongside old ones
- Exit codes: 0=all pass, 1=at least one fail, 2=prerequisite failure

### browser-worker.sh
**Input:** `<command> <host> [options]`
**Purpose:** Remote browser worker lifecycle management. Starts/stops a browser daemon on a remote host via SSH, manages SSH tunnel, and writes a local state file so callers work transparently.

Commands:
- `start <host> [--port N] [--local-port N]` — Start remote daemon + SSH tunnel
- `stop <host>` — Tear down tunnel and remote daemon
- `status <host>` — Report tunnel and remote daemon status

Key behavior:
- Remote config from `project_capabilities` where `type='remote-browser'`
- SSH tunnel from local port to remote daemon port
- Local state file points to tunneled endpoint
- Guards against running alongside a local daemon
- Tunnel PID tracked in `yoke/browser/.tunnel-pid`
- Exit codes: 0=success, 1=failed, 2=daemon not running, 3=usage error

## Configuration Scripts

### config-helper.sh
**Input:** `get <key> [default]`
**Purpose:** Read project configuration from `yoke/config`. Simple key=value format with `#` comments. Missing file or key returns the default value. Exit 0 always (config is advisory — missing config never breaks anything). Used by most other scripts to read configurable settings (base branch, CI timeout, deploy environments, etc.).

### merge-settings.sh
**Input:** `<path-to-settings.json>`
**Purpose:** Deterministically merges Yoke's 6 required permission rules plus the `UserPromptSubmit` (`harness-session-start.sh`) and `Stop` (`harness-session-end.sh`) hooks into a target project's `.claude/settings.json`. Creates the file if it does not exist. Handles empty files, existing permissions, existing hooks, and partial rule sets.

The 6 hardcoded rules:
- `Bash(yoke-engineer:*)`
- `Write(yoke-engineer:*)`
- `Edit(yoke-engineer:*)`
- `Read(*)`
- `Grep(*)`
- `Glob(*)`

Key behavior:
- Union merge: adds only missing permission rules, preserves all existing user rules
- Also merges `hooks.UserPromptSubmit` entry for `harness-session-start.sh` and `hooks.Stop` entry for `harness-session-end.sh` — additive merge, preserves existing user hooks, idempotent
- Order: existing rules first, then new Yoke rules appended
- Atomic write via temp file (`${target}.tmp.$$` + `mv`)
- Idempotent: running twice produces no diff
- Uses `sort_keys=True` for deterministic output (may reorder keys on first run)
- Handles 6 input states: file missing, file empty, file with existing allow rules, file with other keys but no permissions, file with permissions but no allow subkey, file with existing hooks but no Yoke hook entry
- Requires `python3` in PATH (inline Python heredoc, same pattern as `json-helper.sh`)

## Service & Integration Scripts

### service-client.sh
**Input:** `<subcommand> [args]`
**Purpose:** Shell adapter for the Python domain layer. Thin wrapper that delegates correctness-critical decisions to the Yoke Python service via `runtime/api/service_client.py`.

Subcommands:
- `approve-check <flow-id> <current-stage>` — Check if stage requires approval
- `active-queue [--project P] [--fields "f1,f2,..."]` — Query active work queue
- `classify-status <status> [--frozen 0|1] [--has-active-run 0|1]` — Classify item board bucket
- `validate-status <status>` — Check if status is valid
- `validate-transition <from> <to> [--item-type TYPE]` — Check if status transition is valid (omit flag for epic/default)

Key behavior:
- Handles path resolution and `YOKE_DB` propagation
- Exits with the Python client's exit code

### timeout-portable.sh
**Input:** `<seconds> <command> [args...]`
**Purpose:** POSIX-compatible timeout for commands. Works on stock macOS without GNU coreutils. Uses background process + kill.

Exit codes: 0-123 = command's own exit code, 124 = timed out, 125 = usage error

## Network Helper Scripts

### gh-retry.sh
**Input:** `<gh-args...>` (same arguments as `gh`)
**Purpose:** Wrapper around GitHub CLI with exponential backoff. Retries on rate limit (HTTP 403) and transient errors (502, 503). Max 3 retries with 5s/15s/45s backoff. Logs retries to stderr. Passes through stdout and exit code. Used by merge-worktree.sh, sync-to-github.sh, backlog-registry.sh, and update-status.sh for critical `gh` operations.

## Path Resolution Scripts

### resolve-paths.sh
**Input:** `<mode> [args]`
**Purpose:** Canonical path resolver for Yoke repo roots. Centralizes the three-tier fallback pattern (`$CLAUDE_PROJECT_DIR` -> `git rev-parse --show-toplevel` -> CWD tree-walk) into a single reusable interface.

Modes:
- `main` — Absolute path to main repo root (never a worktree root). If CWD is inside a worktree directory, strips the worktree path component to return the main root.
- `worktree` — Absolute path to the worktree root (or main root if not in a worktree). Uses `git rev-parse --show-toplevel` directly.
- `main-file <path>` — Absolute path to a file relative to the main repo root. Combines `main` mode with the provided relative path.
- Also: `yoke-root`, `db`, `config`, `config-example`, `backlog`, `board`, `docs`, `epics`, `releases`, `ouroboros`, `designs`, `backups` — Absolute paths to the corresponding `yoke/` subdirectory (always main repo, never worktree).

Key behavior:
- Three-tier fallback: `$CLAUDE_PROJECT_DIR` (tier 1) -> `git rev-parse --show-toplevel` (tier 2) -> walk up from CWD looking for `yoke/yoke.db` (tier 3)
- Worktree stripping: detects `/{worktrees_dir}/` in the resolved path and strips everything from that component onwards. The `worktrees_dir` value is read from `config-helper.sh` (default: `.worktrees`).
- Output: one line to stdout, no trailing slash
- Exit codes: 0 on success, 1 on failure (error/usage to stderr)

### write-to-main.sh
**Input:** `<append|write> <relative-path>` (content via stdin)
**Purpose:** Shared-state file writer with advisory locking. Writes to files on the main repo root regardless of CWD. Primary mechanism for agents to write shared-state files (ouroboros log, backlog items) from worktrees without worktree/main path confusion.

Subcommands:
- `append` — Appends stdin content to the file at the main repo root. Creates file and parent directories if needed.
- `write` — Overwrites the file at the main repo root with stdin content. Creates file and parent directories if needed.

Key behavior:
- Resolves the main repo root using the same three-tier fallback as `resolve-paths.sh` (inlined per FR-B.2, not a subprocess call)
- Worktree-aware: if invoked from a worktree CWD, writes to the main repo root, not the worktree copy
- Advisory locking via `lock-helper.sh` — acquires a per-file lock (`<file>.lock`) before writing, releases after. Content is read from stdin before lock acquisition to minimize lock hold time.
- Uses `printf '%s\n'` to avoid shell echo flag interpretation (`-n`, `-e`)
- Exit codes: 0 on success, 1 on failure (error/usage to stderr)

## Data Helper Scripts

### json-helper.sh
**Input:** `<command> [args]`
**Purpose:** Safe JSON manipulation via Python's `json` module. Replaces fragile sed/awk JSON operations.

Commands: `get`, `set`, `set-int`, `increment`, `append`, `create`, `csv-to-array`.

### yaml-helper.sh
**Input:** `<command> [args]`
**Purpose:** Safe YAML frontmatter manipulation via Python. Replaces fragile sed/awk YAML operations in backlog-registry.sh, rebuild-board.sh, and sync-to-github.sh.

Commands:
- `get <file> <field>` — Read a frontmatter field value
- `set <file> <field> <value>` — Update a frontmatter field (atomic write, auto-updates `updated` timestamp)
- `strip <file>` — Output file body (after frontmatter) to stdout
- `strip-to-file <file> <outfile>` — Same as strip but writes to a file
- `first-heading <file>` — Extract first markdown heading from body
- `create <file> <field1=value1> ...` — Create new file with YAML frontmatter from key=value pairs

Key behavior:
- Only handles simple `key: value` frontmatter delimited by `---` lines
- Atomic writes via temp file + mv (same pattern as json-helper.sh)
- `set` auto-updates the `updated` timestamp field if present
- `set` acquires a per-file advisory lock (`<file>.lock`) via `lock-helper.sh` to prevent concurrent writes from corrupting frontmatter. Use `--no-lock` flag to skip locking when the caller already holds a lock.
- Requires `python3` in PATH

## Locking Scripts

### lock-helper.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** Shared advisory locking via `mkdir` (POSIX-portable, atomic on all platforms). Provides two functions: `acquire_lock <lockdir>` and `release_lock <lockdir>`.

Functions:
- `acquire_lock <lockdir>` — Creates the lock directory atomically via `mkdir`. Retries up to `lock_retries` times with `lock_sleep_ms` delay between attempts. Detects and removes stale locks older than `lock_stale_seconds`. Returns 1 if lock cannot be acquired after all retries.
- `release_lock <lockdir>` — Removes the lock directory via `rmdir`. Always succeeds (failure silently ignored).

Configuration (via `config-helper.sh`):
- `lock_retries` — Max retry attempts (default: 50)
- `lock_sleep_ms` — Sleep between retries in milliseconds (default: 100)
- `lock_stale_seconds` — Age in seconds before a lock is considered stale and auto-removed (default: 60)

Key behavior:
- Uses `mkdir` for atomic lock acquisition (POSIX guarantee: `mkdir` is atomic on compliant filesystems)
- Stale lock detection via `stat` modification time (BSD `stat -f %m` with GNU `stat -c %Y` fallback)
- Millisecond-to-seconds conversion for `sleep` portability
- Sourced by `backlog-registry.sh`, `yaml-helper.sh`, and `rebuild-board.sh` for parallel-safe operations

### merge-lock.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** DB-based merge lock for cross-session coordination. Prevents concurrent merge operations from colliding when multiple conduct sessions attempt merges simultaneously. Uses the `merge_locks` table in `yoke/yoke.db` (created by `schema-db.sh init`).

Requires: `$YOKE_DB` and `$SCRIPT_DIR` set by the sourcing script.

Functions:
- `merge_lock_check` — Queries `merge_locks` for active locks. Auto-deletes expired rows (past `expires_at`) and stale rows (dead PID via `kill -0`). Returns 0 if no blocking lock exists, returns 1 with diagnostic message to stderr if blocked.
- `merge_lock_acquire <branch> [epic_id]` — Inserts a lock row with a generated `session_id` (`PID-epoch`), the specified branch, optional `epic_id` (NULL if omitted), and computed `expires_at` (current time + `merge_lock_ttl_minutes` config, default 30). Sets module-level vars `_MERGE_LOCK_SESSION_ID` and `_MERGE_LOCK_BRANCH`.
- `merge_lock_release` — Deletes the row matching `_MERGE_LOCK_SESSION_ID` and `_MERGE_LOCK_BRANCH`. No-op if no lock is held (vars are empty). Clears module-level vars after deletion.
- `merge_lock_force_clear` — Deletes ALL rows from `merge_locks`. Emergency recovery function used by merge SKILL.md `--force-lock` flag.

Configuration (via `config-helper.sh`):
- `merge_lock_ttl_minutes` — Lock TTL in minutes (default: 30)

Key behavior:
- Smart stale detection: extracts PID from session_id, checks with `kill -0`. Dead PIDs are treated as stale and auto-deleted before TTL expiry.
- All SQLite operations use `.timeout 5000` (5-second busy wait) to handle concurrent access.
- Sourced by `merge-worktree.sh` for the merge operation lifecycle (check → acquire → merge → release).

## Session Timing Scripts

### timing-helper.sh
**Input:** Library — source this file; do not execute directly.
**Purpose:** Session timing instrumentation library. Provides three functions for timestamping script phases to structured log files in `yoke/ouroboros/session-logs/`. All functions are no-ops when `session_timing_enabled` is `false` (the default). Safe to source in `set -e` scripts via guard pattern: `. "$SCRIPT_DIR/timing-helper.sh" 2>/dev/null || true`.

Functions:
- `timing_init <script_name> [note]` — Creates log directory and file, writes START entry, sets `TIMING_LOG`, `TIMING_START`, `TIMING_LAST`, `_TIMING_SCRIPT` environment variables. Runs log rotation (deletes files older than `session_timing_retain_days`).
- `timing_mark <STEP_NAME> [note]` — Appends a timestamped entry with `elapsed=` (since last mark) and `total=` (since init) durations. Updates `TIMING_LAST`.
- `timing_end [exit_code]` — Writes an END entry with elapsed, total, and exit code. Defaults to exit code 0.

Configuration (via `config-helper.sh`):
- `session_timing_enabled` — true/false (default: false). When false, all functions are no-ops.
- `session_timing_retain_days` — days to keep log files (default: 30)

Log entry format: `{epoch} {ISO8601_UTC} {script_name}/{STEP_NAME} elapsed={N}s total={M}s [{note}]`
Log file naming: `YYYYMMDD-HHMMSS-{script_name}-{PID}.log`

### timing-report.sh
**Input:** `<log-file-path>`
**Purpose:** Human-readable report generator for session timing logs. Parses a session log file produced by `timing-helper.sh` and outputs a formatted table with columns: STEP, ELAPSED, CUMULATIVE. Marks the slowest phase with `<- slowest` suffix. Includes a header line with session name and start time, and a footer with total elapsed time. Uses only POSIX sh and awk (BSD-compatible). Exits 0 on success, 1 if no file argument or file not found.

## Test Scripts

Test scripts live in `.agents/skills/yoke/scripts/tests/`. All are POSIX sh, executable, and self-contained (create everything they need in `/tmp`).

### test-body-sync.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `backlog-registry.sh sync-body` subcommand and HC-body-drift body drift detection. Tests 1-3 validate sync-body directly. Tests 4-7 exercise HC-body-drift via `backlog-resync.sh --doctor-format` (body drift detection is now delegated from doctor.sh to backlog-resync.sh).

Test cases:
- **Test 1:** sync-body success -- mock gh called with `issue edit` and `--body-file`, exits 0
- **Test 2:** sync-body failure -- exits 0 (graceful degradation), stderr contains Warning and gh error output (not suppressed by `2>/dev/null`)
- **Test 3:** sync-body with `github_issue: null` -- exits 0, no gh calls made, silent no-op
- **Test 4:** HC-body-drift WARN -- empty GitHub body with local content: `backlog-resync.sh --doctor-format` flags as body drift
- **Test 5:** HC-body-drift WARN -- heading-only GitHub body (1 line vs 5 local): `backlog-resync.sh --doctor-format` flags as body drift
- **Test 6:** HC-body-drift PASS -- matching GitHub body: `backlog-resync.sh --doctor-format` reports PASS
- **Test 7:** HC-body-drift --fix -- body drift scenario triggers sync-body (mock gh receives `issue edit` with `--body-file`)

Key behavior:
- Tests 1-3: Creates fresh temp directories with mock `gh` for each test (success and failure variants)
- Tests 4-7: Creates full mock environments with pre-built JSON cache files (avoids echo/printf escape interpretation issues with multiline JSON body strings). HC-body-drift is now tested via `backlog-resync.sh --doctor-format`, not doctor.sh internals.
- Hard-codes gh-log path in mock scripts (avoids subshell env propagation issues)
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail
- Cleanup via trap on exit (removes all temp dirs)

### test-update-status.sh
**Input:** None (self-contained)
**Purpose:** Test suite for DB-native `update-status.sh`. Also tests HC-comment-sync comment sync delegated to `backlog-resync.sh --doctor-format`. Validates close-at-completed, label aliasing, label normalization, error logging, DB-only interface enforcement, HC-comment-sync content validation and --fix mode, and flag parsing.

Test cases:
- **Test 1 (B1):** Close at completed — `gh issue close` called when status reaches completed
- **Test 2 (B2):** Label alias — `status:done` used instead of `status:completed`
- **Test 3:** Old label alias — `status:done` on removal for completed status
- **Test 4:** completed then done — both transitions exit 0, two close calls
- **Test 9:** --fix --file flags work together (no parse error)
- **Test 10:** Error logging — comment-post failure logged to retry log
- **Test 11:** Error logging — label-swap failure logged to retry log
- **Test 12:** Error logging — issue-close failure logged to retry log
- **Test 13:** DB-only interface rejects removed `reconcile-github` mode (usage error)
- **Test 14:** DB-only interface rejects legacy status-file argument shape (usage error)
- **Test 15:** DB-native status update succeeds without `gh` available
- **Test 16 (HC-comment-sync):** PASS when comments contain `**Status:**` marker (exercised via `backlog-resync.sh --doctor-format`)
- **Test 17 (HC-comment-sync):** WARN when comments lack `**Status:**` marker (exercised via `backlog-resync.sh --doctor-format`)
- **Test 18 (HC-comment-sync):** --fix posts synthetic status comment via `backlog-resync.sh --fix --doctor-format`
- **Test 26:** Stale status labels — removes legacy `status:in_progress` while adding canonical `status:implementing`

Key behavior:
- Creates fresh temp directories with mock `gh` for each test
- Tests 10-12 use failing mock `gh` variants to trigger retry log writes
- Tests 13-15 verify interface and dependency behavior after legacy mode removal
- Tests 16-18 use mock `gh` returning configurable comment bodies for HC-comment-sync content validation (now tested via `backlog-resync.sh --doctor-format`, not doctor.sh internals)
- Cleanup via trap on exit (removes all temp dirs)
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail

### backlog-resync pytest coverage
Behavioral coverage lives in `runtime/api/engines/test_resync_full.py` (YOK-1246). The shell launcher `backlog-resync.sh` is a thin delegator to `python3 -m runtime.api.engines.resync`.

### test-merge-worktree.sh
**Input:** None (self-contained)
**Purpose:** Regression test suite for `merge-worktree.sh`. Exercises all four fixed bugs (A1-A4) and YOK-96 acceptance criteria in isolated temp git repos with mock `gh` CLI.

Test cases:
- **Bug A1:** Dirty `data/BOARD.md` on main auto-committed before merge
- **Bug A2:** `yoke/ouroboros/log.md` conflict during rebase (originally tested append-only auto-resolution; now tests normal conflict behavior since `APPEND_ONLY_FILES` was removed)
- **Bug A3:** `gh pr merge` called with CWD equal to repo root (not worktree)
- **Bug A4:** Worktree removed before branch deletion (correct ordering)
- **YOK-96:** Dirty user-authored file in worktree exits 4
- **YOK-96:** Clean worktree exits 0
- **YOK-96:** Safety stash created and cleaned up on success
- **Body-diff:** Frontmatter-only backlog change auto-committed (Yoke-managed)
- **Body-diff:** Body content change blocks merge with exit 4 (user-authored)
- **YOK-538:** Branch-modified doc file NOT auto-resolved — manual resolution triggered (conflict returns exit 3)
- **YOK-538:** Unmodified doc file auto-resolved by keeping main's version (backward compatibility preserved)
- **YOK-1205:** Trial merge passes with additive-only conflict (both sides add, no deletions)
- **YOK-1205:** Trial merge exits 3 for overlapping conflict with structured `CONFLICT|file|classification` output
- **YOK-1205:** Real merge auto-resolves additive conflict via union merge, both sides' content preserved
- **YOK-1205:** Existing generated/doc/yoke-gen resolution unchanged alongside additive path
- **YOK-1205:** Classifier rejects file with deletions (correctly classified as overlapping)

Key behavior:
- Creates a fresh temp git repo with bare origin, main branch, feature branch, and worktree for each test
- Mock `gh` records CWD at invocation (for Bug A3 assertion) and performs real git merge on origin (for post-merge verification)
- Each test is a named function with PASS/FAIL output per assertion
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail
- Cleanup via trap on exit (removes all temp dirs)

### test-timing-helper.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `timing-helper.sh` and `timing-report.sh`. Validates timing instrumentation functions in isolated temp directories with mock `config-helper.sh`.

Test cases:
- `timing_init` creates log directory and file with correct `YYYYMMDD-HHMMSS-{name}-{PID}.log` naming
- `timing_init` writes START entry as first line
- `timing_mark` appends entries with `elapsed=` and `total=` values
- `timing_end` writes END entry with exit code
- Disabled mode: with `session_timing_enabled=false`, no files are created
- Log rotation: files older than retain days are deleted
- `timing-report.sh` output format and slowest-phase marking
- Guard sourcing: a `set -e` script sourcing nonexistent helper via guard pattern does not exit

Key behavior:
- Same framework pattern as `test-merge-worktree.sh` (pass/fail functions, cleanup trap, summary line)
- Exit 0 if all pass, exit 1 if any fail


### test-project-aware-sync.sh
**Input:** None (self-contained)
**Purpose:** Historical test suite for shell-era per-project token infrastructure and cross-project sync functions in `sync-helper.sh` (YOK-683). Current tests cover the canonical project GitHub auth resolver instead.

### test-sync-progress-cross-project.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `sync-progress.sh` cross-project support (YOK-683). Validates that `gh issue comment` calls include the correct `-R` flag for non-yoke project items, with per-project token resolution.

### test-sync-to-github-cross-project.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `sync-to-github.sh` cross-project support (YOK-683). Validates that epic-level `gh issue` calls (label addition, body sync) include the correct `-R` flag for non-yoke project items.

### test-cross-project-audit.sh
**Input:** None (self-contained)
**Purpose:** End-to-end audit test for cross-project GitHub sync (YOK-683). Validates that all sync scripts (`sync-helper.sh`, `update-status.sh`, `sync-progress.sh`, `sync-to-github.sh`, `backlog-resync.sh`, `doctor.sh`) correctly handle cross-project items with proper `-R` flags and per-project token isolation.

### test-harness-session-start.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `harness-session-start.sh`. Exercises fire-once guard, shared prompt-doctrine injection, smart truncation, graceful degradation, and project root detection across multiple test cases in isolated temp git repos.

Test cases (8 named functions):
- **Valid JSON input:** Extracts session_id from JSON payload, emits orientation block
- **Empty JSON input:** Falls back to PID-based session ID, still emits orientation
- **Malformed stdin:** Handles non-JSON input gracefully, still emits orientation
- **Fire-once guard:** Second invocation with same session_id produces no output
- **No git repo:** Exits silently when not in a git repository
- **No plan file:** Emits orientation without plan section when BOARD.md is missing
- **Smart truncation:** Large plan file triggers Done-section dropping and line-count truncation
- **No Yoke marker:** Exits silently when `yoke.db` is absent (non-Yoke repo)

Key behavior:
- Creates fresh temp git repos with Yoke directory structure for each test
- Copies `harness-session-start.sh` and `config-helper.sh` into test repos
- Cleanup via trap on exit (removes all temp dirs)
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail

### test-bootstrap-helper.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `runtime/harness/bootstrap-helper.sh` and `bootstrap-spec.json`. Validates required-file ordering, prompt-philosophy inclusion, compact/full rendering, and drift protection against re-embedding the doctrine or shared read list in harness shells.

### test-resolve-paths.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `resolve-paths.sh`. Exercises all three modes (main, worktree, main-file) across multiple test cases in isolated temp git repos with real git worktrees (not mocked).

Test cases:
- **CLAUDE_PROJECT_DIR set:** Returns the `$CLAUDE_PROJECT_DIR` path directly
- **git rev-parse fallback:** Without `$CLAUDE_PROJECT_DIR`, returns repo root via git
- **main mode from worktree:** Returns the main repo root (not worktree root) when CWD is inside a worktree
- **worktree mode from worktree:** Returns the worktree root when CWD is inside a worktree
- **main-file mode:** Returns absolute path to a file relative to main repo root
- **No arguments:** Exits 1 with usage message
- **Outside git repo:** Exits 1 with error message

Key behavior:
- Creates real git worktrees (not mocked) for worktree mode tests
- Copies `resolve-paths.sh` and `config-helper.sh` into test repos so `SCRIPT_DIR`-relative lookups work
- Path canonicalization via `pwd -P` to handle `/tmp` -> `/private/tmp` on macOS
- Cleanup via trap on exit (removes all temp dirs)
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail

### test-write-to-main.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `write-to-main.sh`. Exercises append, write, concurrent locking, and error handling across multiple test cases in isolated temp git repos with real git worktrees.

Test cases:
- **Append from worktree CWD:** Appends content to a file at the main repo root (not the worktree root), verifies file does not exist in worktree
- **Write from worktree CWD:** Overwrites file at main repo root, verifies overwrite replaces prior content
- **Concurrent append:** Two parallel appends via background processes, verifies both entries present with no corruption (exactly 2 lines)
- **Unknown subcommand:** Exits 1 with usage message mentioning the invalid subcommand
- **Missing file argument:** Exits 1 with usage message mentioning missing argument

Key behavior:
- Creates real git worktrees (not mocked) for worktree tests
- Copies `write-to-main.sh`, `lock-helper.sh`, and `config-helper.sh` into test repos
- Path canonicalization via `pwd -P` for macOS compatibility
- Concurrent test uses background processes (`&`) with `wait` for parallel execution verification
- Cleanup via trap on exit (removes all temp dirs)
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail

### test-migrate-to-sqlite.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `migrate-to-sqlite.sh` and `generate-backlog-md.sh`. Tests the full round-trip: .md -> DB (migrate) -> .md (generate) and verifies fidelity, edge cases, and graceful degradation. All tests create isolated temp directories in `/tmp`.

Test cases:
- **Test 1:** Round-trip fidelity — standard item with all fields populated
- **Test 2:** Round-trip fidelity — null optional fields
- **Test 3:** Round-trip fidelity — special characters in title (em-dash, backticks, parentheses)
- **Test 4:** Round-trip fidelity — body with `---` separator patterns
- **Test 5:** Body with single quotes and contractions
- **Test 6:** Frozen boolean mapping (`false` -> `0` -> `false`, `true` -> `1` -> `true`)
- **Test 7:** Null string mapping (`null` -> SQL NULL -> `null`)
- **Test 8:** Integer field handling (rework_count stored and rendered as integers)
- **Test 9:** Idempotent migration (run twice, count unchanged)
- **Test 10:** Missing DB graceful degradation (generate exits 0)
- **Test 11:** Item not found graceful degradation (generate exits 0)
- **Test 12:** `--all` flag (3 items, verify all regenerated)
- **Test 13:** Non-canonical field order normalization (reordered to canonical)
- **Test 14:** Missing fields (older items without frozen, etc.)
- **Test 15:** merged_at preservation (present when set, absent when NULL)
- **Test 16:** Byte-perfect round-trip (diff original vs regenerated)
- **Test 17:** Title with backticks
- **Test 18:** Multiple items counted correctly after migration

Key behavior:
- Creates fresh temp directories per test with cleanup trap
- Exercises both `migrate-to-sqlite.sh` and `generate-backlog-md.sh` together
- Validates DB types (typeof), SQL NULL via COALESCE, and frontmatter text output
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail

### test-backlog-registry-sqlite.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `backlog-registry.sh` SQLite write path. Tests CRUD operations, sync operations, dedup-search, special characters, concurrency, dry-run, and edge cases for the SQLite-backed backlog registry. All tests create isolated temp directories in `/tmp`.

Coverage areas:
- Add operations — basic insert, frontmatter generation, sequential IDs, dry-run no-op
- Update operations — single field, multi-field, done-transition cleanup, rework counter
- List and query operations — filtered list, get-next-id, item row query
- Sync operations — sync-item, close-issue, post-comment, sync-body, sync-labels
- Dedup and search — dedup-search, body sync with DB, rebuild-board trigger
- Special characters and edge cases — em-dash, backticks, single quotes, unicode, empty body
- Concurrency — parallel adds, parallel updates, lock contention
- Dry-run and error handling
- Status comment auto-posting, no-comment for non-status updates, no-error without github_issue, batch-update, lazy label color lookups
- Terminal-state sync details, including `close_issue` on `cancelled` and `status:<status>` label creation during `sync_item`

Key behavior:
- Creates fresh temp directories per test with YOKE_ROOT override and mock `gh`
- Initializes DB via `schema-db.sh init` for each test
- Validates both DB state (via sqlite3 queries) and .md file generation
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail

### test-ouroboros-db.sh
**Input:** None (self-contained)
**Purpose:** Test suite for `ouroboros-db.sh`. 29 descriptive test cases covering all 7 subcommands (insert-entry, insert-wrapup, list-entries, list-wrapups, mark-reviewed, mark-archived, generate-wrapup), dedup behavior, `--body-stdin`, `--unreviewed`, edge cases, and the named-flag flows (`--agent`, `--context`, `--category`, `--observation`, `--timestamp`, `--body-stdin`, validation errors, unknown flag rejection, mutual exclusion, router passthrough). All tests create isolated temp directories in `/tmp`.

Key behavior:
- Creates fresh temp directories per test with YOKE_ROOT override
- Initializes DB via `schema-db.sh init` for each test
- Validates DB state via sqlite3 queries and generated file contents
- Summary line: `N passed, M failed`
- Exit 0 if all pass, exit 1 if any fail

### Additional Test Suites

The following test scripts follow the same patterns (self-contained, temp dirs, `N passed, M failed` summary):

**DB & Migration Tests:**
- `test-backup-db.sh` — Local backup helper (backup-db.sh): WAL-mode backup, retention pruning, staleness, hard-block, S3 upload (mocked)
- `test-yoke-db.sh` — Unified DB router (yoke-db.sh) test suite
- `test-shepherd-db.sh` — Shepherd DB operations
- `test-project-db.sh` — Project domain CRUD (project-db.sh)
- `test-flow-db.sh` — Deployment flow CRUD (flow-db.sh)
- `test-designs-db.sh` — Design document CRUD (designs-db.sh)
- `test-release-notes-db.sh` — Release notes CRUD (release-notes-db.sh)
- `test-render-body.sh` — Render-body.sh and structured field access (render-body.sh, item_sections CRUD, field read/write via yoke-db.sh)
- `test-query-items.sh` — Query items read path
- `test-migrate-to-sqlite.sh` — Backlog migration
- `test-schema-extensions.sh` — Schema extension validation
- `test-schema-gate.sh` — Schema gate enforcement

**Backlog & Sync Tests:**
- `test-backlog-label-sync.sh` — GitHub label synchronization
- `test-backlog-registry-sqlite.sh` — Registry CRUD (documented above)
- `test-dedup-body-scan.sh` — Dedup body content scanning
- `test-dedup-github-issues.sh` — GitHub issue deduplication
- `test-frozen-label-sync.sh` — Frozen label sync
- `test-generate-backlog-md.sh` — Backlog markdown generation
- `test-sync-body-silent-fail.sh` — Sync body failure handling
- `test-dry-run.sh` — Dry-run mode across operations

**Board Tests:**
- `test-rebuild-board-throttle.sh` — Board rebuild throttling
- `test-art-weight-selection.sh` — Art weight selection algorithm
- `test-ascii-art.sh` — ASCII art variant rendering
- `test-zero-variant-art.sh` — Zero-variant art fallback
- `test-board-velocity-sparkline.sh` — Velocity sparkline rendering
- `test-board-wip-weather.sh` — WIP gauge and weather heuristic
- `test-stats-meters.sh` — Stats meter rendering

**Doctor & Health Tests:**
- `test-stale-body-guard.sh` — Structured render failure guard + HC-stale-body

**Deployment Pipeline Tests:**
- `test-executors.sh` — Executor scripts (exec-auto.sh, exec-health-check.sh, exec-script.sh), flow-db github-actions-workflow validation
- `test-github-actions.sh` — GitHub Actions integration (trigger, poll, find-run) with mocked gh CLI
- `test-deploy-pipeline.sh` — Deploy pipeline orchestrator (stage iteration, resume, failure handling, events)

**Workflow Tests:**
- `test-create-epic-worktree.sh` — Worktree creation (unified `create-worktree.sh`)
- `test-done-transition-deploy-guard.sh` — Done transition deployment flow guard (YOK-576)
- `test-done-transition-gaps.sh` — Done transition gap handling
- `test-done-transition-retry.sh` — Done transition Step 6 retry logic (YOK-442)
- `test-done-transition-sim-gate.sh` — Done transition simulation gate
- `test-merge-worktree.sh` — Merge worktree pipeline
- `test-merge-worktree-db-lock.sh` — Merge worktree DB lock contention
- `test-merge-lock.sh` — Merge lock CRUD operations
- `test-merge-guard-sun552.sh` — Merge guard (YOK-552)
- `test-prd-validate.sh` — PRD validation gate
- `test-item-depends-on.sh` — Item dependency resolution
- `test-classify-dirty-files.sh` — Dirty file classification

**Hook & Utility Tests:**
- `test-lint-sqlite-cmd.sh` — Lint hook enforcement
- `test-lint-tc-label.sh` — TC/HC label lint hook (blocks sequential TC-N and numeric HC filenames)
- `test-on-agent-stop.sh` — Agent stop hook
- `test-on-bash-complete-root.sh` — Bash complete hook project root resolution
- `test-hook-helpers.sh` — Hook helpers library
- `test-bootstrap-helper.sh` — Neutral bootstrap helper + drift guard
- `test-harness-session-start.sh` — Session startup hook
- `test-harness-sessions-parity.sh` — Session claim parity, harness-session-end.sh, merge-settings Stop hook (YOK-1290)
- `test-resolve-paths.sh` — Path resolution
- `test-write-to-main.sh` — Write-to-main safety
- `test-temp-cleanup.sh` — Temp file cleanup

**Shepherd & Compose Tests:**
- `test-shepherd-log.sh` — Shepherd log rendering
- `test-shepherd-state.sh` — Shepherd state management
- `test-compose-dump-render.sh` — Compose dump/render
- `test-compose-migration3.sh` — Compose migration 3
- `test-compose-task003.sh` — Compose task 003
- `test-compose-task004.sh` — Compose task 004
- `test-compose-absorb.sh` — Compose absorb operation
- `test-conduct-batch-summary.sh` — Conduct batch summary

**Browser Tests:**
- `test-browser-artifact.sh` — Browser QA artifact integration (--qa-run-id flag, metadata, storage paths)

**Shared:**
- `test-helpers.sh` — Shared test library (sourced by other test scripts, not run directly)

## Skill Phase Files

Large skills are decomposed into phase sub-files under `.agents/skills/yoke/{command}/`. Top-level SKILL.md files should stay compact orchestration surfaces that delegate detailed sub-protocols to phase files. HC-skill-phase-size enforces a 250-line limit per phase file, and doctor separately monitors oversized top-level prompt surfaces.

### strategize/

**Purpose:** Guided interactive loop for Strategic Markdown Layer (SML) coherence. 5 phase files with 6 operator checkpoints.

- `refresh.md` — Phase 1: Delta bounding, state gathering, Checkpoint 0 (state refresh confirmation), Checkpoint 1 (problem framing). Emits `SMLRefreshCompleted`.
- `research.md` — Phase 2: Source-backed landscape research, Checkpoint 2 (normative filter). Produces filtered findings for `propose.md`.
- `propose.md` — Phase 3: Draft SML changes, Checkpoint 3 (SML change approval). Emits `SMLChangeProposed` for each proposed change batch.
- `approve.md` — Phase 4: Apply approved SML changes, commit them, Checkpoint 4 (frontier implication check), Checkpoint 5 (tradeoff resolution if needed). Emits `SMLChangeApproved`.
- `finalize.md` — Phase 5: Record comprehensive audit trail and print the session summary. Emits `StrategizeCompleted`.

### Other decomposed skills

- `advance/` — 5 phase files (preflight, worktree, environment, browser-qa, finalize) + `implementing/` sub-skill (4 files: qa-seeding, browser-seeding, test-and-record, implementation)
- `idea/` — 2 phase files (`infer-and-create.md`, `body-and-sync.md`)
- `curate/` — 2 phase files (`cluster-and-ticket.md`, `patterns-and-retro.md`)
- `simulate/` — 4 phase files (`epic-flow.md`, `dispatch-prompts.md`, `autofix-loop.md`, `system.md`)
- `usher/` — 5 phase files (collect, plan, merge, deploy, finalize)
- `shepherd/` — 4 phase files (`design-and-plan.md`, `planning-to-planned-gates.md`, `boss-verdict.md`, `finalize.md`)
- `do/` — loop.md (session offer loop logic)

## Test Case Naming Convention

All test labels in active source test suites under `.agents/skills/yoke/scripts/tests/` MUST use descriptive identifiers. Sequential numeric labels (`TC-<number>`) are **prohibited in new code**. All HC references must use slug form (e.g., `HC-worktree-health`, `HC-schema-drift`).

### TC Label Format

```
TC-{domain}-{description}
```

- **`{domain}`** is derived from the test filename by stripping the `test-` prefix and `.sh` suffix, then abbreviating to a recognizable short form:
  - `test-backlog-registry-sqlite.sh` -> domain `registry`
  - `test-render-body.sh` -> domain `render-body`
  - `test-yoke-db.sh` -> domain `yoke-db`
  - `test-designs-db.sh` -> domain `designs-db`
  - `test-ouroboros-db.sh` -> domain `ouroboros-db`
  - Python QA behavioral coverage -> `runtime/api/test_qa_full.py`
  - Python epic behavioral coverage -> `runtime/api/test_epic_full.py`
  - `test-update-status.sh` -> domain `status`
  - `test-body-sync.sh` -> domain `body-sync`
  - Python resync behavioral coverage -> `runtime/api/engines/test_resync_full.py`
- **`{description}`** is a short kebab-case phrase describing what the test case verifies.

#### Examples

| Legacy Pattern | New Label | Meaning |
|----------------|-----------|---------|
| `TC-<number>` in registry suite | `TC-registry-add-item-basic` | Basic item creation in backlog registry |
| `TC-<number>` in render-body suite | `TC-render-body-spec-field` | Spec field rendered into body |
| `TC-<number>` in yoke-db suite | `TC-yoke-db-epic-task-list` | Epic task listing via unified router |
| `TC-<number>` in update-status suite | `TC-status-close-at-completed` | Issue closed when status reaches completed |
| `TC-<number>` in resync suite | `TC-resync-state-drift` | State drift detected (local done, GitHub OPEN) |

### Why Descriptive Labels

Sequential numeric labels cause merge conflicts when multiple branches add tests to the same file — each independently appends the "next" number. Descriptive labels are conflict-free (unique by meaning), grep-friendly, and self-documenting.

### HC Test File Naming Convention

Doctor health-check test files follow the pattern:

```
test-doctor-hc-{slug}.sh
```

Where `{slug}` matches the runtime HC identifier used by `doctor.sh` (the descriptive slug from the YOK-724 migration, e.g., `schema-drift`, `stale-wip`, `title-length`).

- **Single-check suites** tested one HC and used the exact runtime slug (e.g., `test-doctor-hc-schema-drift.sh`).
- **Grouped suites** test multiple related HCs and use a documented grouped slug that clearly names the covered checks: `test-doctor-hc-template-checks.sh` (covering `HC-stray-project-files` and `HC-template-project-drift`)

Numeric doctor-test filenames are **prohibited**. All doctor-test files now use slug-based names (YOK-1206 completed the migration).

### Prohibition Rule

The following patterns are prohibited in new or modified code under active source paths:

- `TC-[0-9]+` labels in test suites (use `TC-{domain}-{description}` instead)
- `HC-[0-9]+` references in test files, docs, config, and agent files (use descriptive HC slugs instead)
- Numeric doctor-test filenames matching `test-doctor-hc[0-9]*.sh` (use `test-doctor-hc-{slug}.sh` instead)

An automatic lint guard enforces these rules on file-create and file-edit paths used in this repo.

## Calling Conventions

- All scripts exit 0 on success, 1 on error
- All read paths relative to the epic directory
- JSON manipulation via `json-helper.sh` (Python `json` module, no jq dependency)
- Legacy YAML frontmatter manipulation via `yaml-helper.sh` (Python, no PyYAML dependency) — retained for any remaining YAML parsing needs
- Backlog item reads via SQL queries against `yoke/yoke.db` (`sqlite3` inline or `item-db.sh` sourced library)
- Python `json` module via inline heredoc for structural JSON operations (merge, deep update) — same pattern used by `json-helper.sh`, `yaml-helper.sh`, and `merge-settings.sh`
- Portable sed: `sed '...' file > tmp && mv tmp file`
- BSD awk: `skip==0{print}` not `!skip{print}`
