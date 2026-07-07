# Hooks Reference

*Last updated: 2026-04-06 (YOK-1278 guarded Stop-hook shutdown docs)*

Yoke uses Claude Code hooks to make orchestration deterministic. Status updates, progress syncing, and cleanup happen via shell scripts -- not by LLM judgment.

## Hook Types

| Hook | Scope | Script | Purpose |
|---|---|---|---|
| UserPromptSubmit | Main session | `harness-session-start.sh` | Injects orientation context (prompt doctrine + startup reads + recent commits + board) on first user prompt; writes session markers; emits `AgentSessionStarted` event |
| Stop | Main session | `harness-session-end.sh` | Force-ends the active session through the shared guarded end-session path and exits 0 when no live session exists |
| PreToolUse (Bash) | Main session + all agents | `lint-sqlite-cmd.sh` | Blocks direct sqlite3, `!=` in SQL, escaped operators, guarded scripts, BSD-incompatible awk, `claude` CLI, conflict markers, `gh` without `-R`, wrong SQL column names, dynamic PRAGMA validation, direct terminal-status write blocking, browser QA run blocking, DDL detection |
| PreToolUse (Bash) | Main session + all agents | `lint-event-registry.sh` | Validates `emit-event.sh` event names against `event_registry` table |
| PreToolUse (Bash) | Main session | `lint-main-commit.sh` | Blocks `git commit` on `main` when staged files include implementation code and active items exist |
| PreToolUse (Bash, Write, Edit, Read) | Main session + all agents | `observe-tool-pre.sh` | Emits `ToolCallStarted` for duration correlation in PostToolUse |
| PreToolUse (Write) | Main session + all agents | `lint-write-path.sh` | Blocks `$$` in file paths; blocks `secrets.*` in `if:` conditions in workflow YAML (YOK-777) |
| PreToolUse (Write/Edit) | Tester, Simulator, Boss | inline echo+exit | Blocks write/edit operations (defense-in-depth) |
| PostToolUse (Bash) | Main session | `sqlite3-error-hook.sh` | Injects hard-stop correction when sqlite3 queries fail; detects and removes stray 0-byte `yoke.db` files; detects row-count collapse after DDL operations (YOK-1296) |
| PostToolUse (Bash) | Engineer | `on-bash-complete.sh` | Syncs progress notes to GitHub issue after each Bash call |
| PostToolUse (Bash, Write, Edit, Read) | Main session | `observe-tool.sh --hook-event PostToolUse` | Emits `ToolCallCompleted` or `ToolCallStructuredExit` structured events with anomaly detection (main-session, no `--agent` flag) |
| PostToolUse (all tools) | 6 worker agents | `observe-tool.sh --agent {type} --hook-event PostToolUse` | Emits `ToolCallCompleted` or `ToolCallStructuredExit` structured events with anomaly detection (per-agent attribution) |
| PostToolUseFailure (Bash, Write, Edit, Read) | Main session | `observe-tool.sh --hook-event PostToolUseFailure` | Emits `ToolCallFailed` structured event (main-session, no `--agent` flag) |
| PostToolUseFailure (all tools) | 6 worker agents | `observe-tool.sh --agent {type} --hook-event PostToolUseFailure` | Emits `ToolCallFailed` structured event (per-agent attribution) |
| SubagentStop | All 7 agents | `python3 -m runtime.api.domain.agent_stop` | Self-discovers active task, sets "stopped" as safety net; auto-commits uncommitted work; emits `AgentSessionStopped` event with `stop_reason` context |

## Registration Locations

Hooks are registered in two places:

1. **`.claude/settings.json`** -- active for the main session and inherited by all subagents. Contains the PreToolUse lint hooks, `harness-session-start.sh`, `harness-session-end.sh`, `sqlite3-error-hook.sh`, main-session `observe-tool.sh --hook-event {PostToolUse|PostToolUseFailure}` (without `--agent`), and main-session `observe-tool-pre.sh`.
2. **Agent adapter frontmatter** (`.claude/agents/yoke-*.md`, owned at `runtime/harness/claude/agents/yoke-*.md` and generated from canonical bodies in `runtime/agents/`) -- per-agent hook wiring. Contains `on-agent-stop.sh`, `on-bash-complete.sh` (Engineer only), `observe-tool.sh --agent {agent-type} --hook-event {PostToolUse|PostToolUseFailure}` (6 worker agents), `observe-tool-pre.sh`, agent-specific `lint-sqlite-cmd.sh`, and write/edit blocks (Tester, Simulator, Boss).

When both locations register the same hook type, Claude Code composes them -- both hooks run independently and each receives the full JSON payload on stdin.

3. **`runtime/harness/codex/open-app.sh` + `.codex/hooks.json`** (Codex harness only) -- optional hook-enhanced mode for Codex sessions. Yoke keeps the working feature enablement in source control via `open-app.sh`, which launches `codex app --enable codex_hooks <repo>`. Requires codex >= 0.118.0-alpha.2. Contains four hooks that delegate to the same Yoke Bash-portable scripts:
   - `SessionStart` -> `on-session-start.sh` (orientation context with fire-once guard)
   - `UserPromptSubmit` -> `on-prompt-submit.sh` (safe-command reminder with fire-once guard)
   - `PreToolUse(Bash)` -> `on-pre-tool-use.sh` (delegates to 6 lint/observation scripts)
   - `PostToolUse(Bash)` -> `on-post-tool-use.sh` (delegates to sqlite3-error-hook and observe-tool)

   Hook scripts live in `runtime/harness/codex/hooks/`. All exit 0 even when delegated scripts are missing. No Codex hook owns canonical telemetry -- they provide optional ergonomics and guardrails only. The Codex hook pack does not cover Write/Edit/Read hooks (no Codex equivalent) or SubagentStop (handled by adapter/core). See `runtime/harness/README.md` for the full parity map.

## Self-Discovery Pattern

Claude Code hooks are static shell commands in agent YAML frontmatter. They only have access to `$CLAUDE_PROJECT_DIR` and standard env vars -- **no custom env vars** (Claude Code doesn't support them). However, hook commands can accept CLI arguments (e.g., `observe-tool.sh --agent engineer --hook-event PostToolUse`), which provides a static way to pass agent identity and hook source from frontmatter to the hook script (YOK-790, YOK-1170).

The hooks `on-agent-stop.sh`, `on-bash-complete.sh`, and `observe-tool.sh` use the same self-discovery pattern:

1. **Find project root:** Use `git worktree list --porcelain` to locate the main repo root (always the first entry). Falls back to `$CLAUDE_PROJECT_DIR` if worktree list is unavailable.
2. **Query dispatch chains:** Read active dispatch chains from `epic_dispatch_chains` DB table via `yoke-db.sh epic`.
3. **Find in-flight task:** Look up `current_task` from the chain record, query its status from `epic_tasks` DB table, and check whether it is still `implementing`.
4. **Act:** `on-agent-stop.sh` sets to "stopped". `on-bash-complete.sh` calls `sync-progress.sh`.

## SubagentStop Hook

**Owner:** `python3 -m runtime.api.domain.agent_stop` (Python-owned since YOK-1366)
**Trigger:** When any subagent finishes (normal or crash)
**Behavior:**
1. **Auto-commit uncommitted work (YOK-410):** Before setting status, checks the worktree for uncommitted changes. If found, stages and commits them with message `chore: auto-commit Engineer uncommitted work [YOK-{N}] (SubagentStop safety net)`. Emits a diagnostic warning to stderr listing the file count and names. This prevents lost work when an Engineer session ends unexpectedly.
2. **Set task to "stopped":** Marks the discovered active task as stopped.
3. **Emit `AgentSessionStopped` event (YOK-407, YOK-1210):** After dispatch chain processing, emits an `AgentSessionStopped` structured event via `runtime.api.domain.events.emit_event`. Captures agent context (epic/task), final task status, auto-commit metadata, and `stop_reason` (one of `completed`, `auto_committed`, or `unexpected_stop`). The event goes to the `events` table for session reconstruction.

**Worktree resolution:** For epic dispatch chains, resolves the worktree from `epic_dispatch_chains.worktree_path`. For issue dispatches (no dispatch chain), resolves from `$CLAUDE_PROJECT_DIR` basename matching the `YOK-{N}` pattern. Guards against the main repo root (no-op if `AGENT_DIR` equals `PROJECT_ROOT`).

**Project root resolution:** Always prefers `git worktree list` (main repo root) over `$CLAUDE_PROJECT_DIR` to ensure `PROJECT_ROOT` resolves to the main repo, not a worktree checkout.

**Status handling:** Only fires the stopped transition for tasks in `implementing` status. Skips `reviewed-implementation`/`implemented`/`release`/`done` -- the parent orchestrator has already advanced the status, so reverting to stopped would be wrong.

**SQLite busy timeout:** All sqlite3 queries use `.timeout 5000` (5 seconds) to handle DB contention during parallel dispatch.

This is **pessimistic by design**. The orchestrator (conduct or dispatch) overrides to the correct canonical status on normal completion:
- After normal completion, the parent flow advances the work to the appropriate next state (`reviewing-implementation`, `reviewed-implementation`, `implemented`, `release`, or `done`)
- After crash, task stays "stopped" (correct)

The auto-commit is **defense-in-depth**. The conduct also runs a post-Engineer commit sweep (YOK-410 FR-3) after the Engineer returns, providing a second safety net.

This means crashed sessions remain visible as "stopped" tasks until the operator re-enters through `/yoke conduct`.

## PostToolUse Hook (Engineer)

**Script:** `on-bash-complete.sh`
**Trigger:** After every Bash tool invocation by the Engineer
**Behavior:**
1. **Yoke script failure detection:** Parses hook JSON input for the command. If it invoked a Yoke script (`.agents/skills/yoke/scripts/`) and the output indicates a non-zero exit, appends a timestamped entry to `yoke/ouroboros/errors.log`.
2. **Worktree-scoped dispatch sync:** Only processes dispatch chains whose `worktree_path` matches `$CLAUDE_PROJECT_DIR`, preventing parallel dispatches from cross-contaminating.
3. Self-discovers active task (same pattern as SubagentStop)
4. cd's to project root before invoking Yoke scripts from the main repo
5. Calls `sync-progress.sh` with the discovered epic ID and current task number
6. `sync-progress.sh` posts unsynced progress notes to GitHub issue as comments

**SQLite busy timeout:** All sqlite3 queries use `.timeout 5000` (5 seconds) to handle DB contention during parallel dispatch (YOK-490).

**Project-aware syncing (YOK-569):** Progress sync resolves the project context from the active dispatch chain. GitHub issue updates include project-scoped labels and metadata, ensuring multi-project deployments route progress to the correct project's tracking.

This gives real-time progress visibility on the GitHub issue page and captures Yoke script errors for Ouroboros analysis.

## PostToolUse/PostToolUseFailure Telemetry Hook (All Sessions)

**Script:** `observe-tool.sh`
**Trigger:** After every tool call (PostToolUse) and every failed tool call (PostToolUseFailure)
**Registration:**
- **Main session:** Registered in `.claude/settings.json` with per-tool matchers (Bash, Write, Edit, Read) for both PostToolUse and PostToolUseFailure. Passes `--hook-event {PostToolUse|PostToolUseFailure}` but does not pass `--agent`, so main-session events have `agent=NULL`.
- **6 worker agents:** Registered in agent frontmatter with `--agent {agent-type} --hook-event {PostToolUse|PostToolUseFailure}` flags (Engineer, Tester, Simulator, Architect, Product Manager, Product Designer). Fires on all tool types (no matcher restriction).

**Behavior:**
1. **Buffer stdin:** Reads the entire hook JSON from stdin into a variable before processing. This ensures each hook in a multi-hook composition receives the full payload independently (Claude Code delivers stdin per-hook).
2. **Parse and extract:** A single `python3` invocation parses the hook JSON, extracts `tool_name`, command text, exit code, and response content.
3. **Anomaly detection:** Checks for five anomaly types:
   - `nonzero_exit` -- tool call returned a nonzero exit code
   - `generated_view_write` -- Write/Edit targeted a generated view file (`BOARD.md`, `designs/*.md`)
   - `nested_cli` -- command spawned a nested `claude` CLI process
   - `benign_failure` -- known-safe failure pattern (YOK-1092), downgraded to INFO severity
   - `retry_loop` -- (registered in enum but not detected here; requires cross-event state)
4. **Emit `ToolCallCompleted` or `ToolCallFailed`:** Builds the full JSON envelope and inserts directly into the `events` table. Failed PostToolUse invocations exit early without emitting so the paired PostToolUseFailure hook can emit the single canonical `ToolCallFailed` row (YOK-1170). The hook bypasses `emit-event.sh` for performance (stays within the 200ms budget).
5. **Persist anomaly flags on the primary row:** When anomalies are present, they are stored in `anomaly_flags` on the emitted tool-call row. There is no separate runtime `AnomalyDetected` event.

**Benign failure handling (YOK-1092):** Known-safe patterns (like stale Edit targets where a prior edit already achieved the desired state) are detected and downgraded from WARN to INFO severity. This reduces transcript noise from expected failure patterns without suppressing genuine errors.

**Performance:** Designed for the hot path. A single `python3` process handles JSON parsing, envelope construction, anomaly detection, and DB insertion -- no subprocess chains.

**Graceful degradation:**
- No-op if the `events` table doesn't exist (dependency tasks not yet merged)
- No-op if `python3` is unavailable
- No-op if `yoke.db` is not found
- Always exits 0 (PostToolUse hooks cannot block agent execution)

**Context enrichment:** Queries `epic_dispatch_chains` via `hook-helpers.sh` `resolve_dispatch_context()` to populate `item_id` and `task_num` fields on emitted events.

**Agent attribution (YOK-790):** Each agent definition passes `--agent <type>` to `observe-tool.sh` in its frontmatter hook command (e.g., `observe-tool.sh --agent engineer --hook-event PostToolUse`). The script parses this arg before buffering stdin and inserts the agent type into the `agent` column of the `events` table. Main-session hooks in `settings.json` do not pass `--agent`, so main-session events have `agent=NULL`. Valid agent types: `engineer`, `tester`, `simulator`, `architect`, `product-manager`, `product-designer`.

**Hook source routing (YOK-1170):** Both main-session and agent hooks pass `--hook-event PostToolUse` or `--hook-event PostToolUseFailure`. The script uses this explicit source to suppress failed PostToolUse emissions so one failed tool call yields exactly one `ToolCallFailed` row.

**`duration_ms` computation (YOK-1069, YOK-1082):** The companion PreToolUse hook `observe-tool-pre.sh` emits `ToolCallStarted` before each tool call when `tool_use_id` is available. `observe-tool.sh` looks up that started row by `tool_use_id`, computes the delta, and populates `duration_ms` in the emitted event.

**Agent frontmatter wiring:** Added to all 6 worker agents' frontmatter (Engineer, Tester, Simulator, Architect, PM, Designer) with `--agent <agent-type> --hook-event <PostToolUse|PostToolUseFailure>` flags. Engineer's existing `on-bash-complete.sh` PostToolUse hook is preserved alongside `observe-tool.sh` -- Claude Code composes multiple hooks on the same event type. The Engineer frontmatter has both a Bash-specific matcher (for `on-bash-complete.sh`) and an unmatched entry (for `observe-tool.sh` on all tools).

**`YOKE_EVENTS_CAPTURE` test mode:** When `YOKE_EVENTS_CAPTURE=1` and `YOKE_EVENTS_FILE` is set, `emit-event.sh` writes JSON envelopes as NDJSON to the capture file instead of inserting into the DB. This enables assertion-based testing of event emission without DB side effects. See `test-events-helpers.sh` for the test harness API.

## PreToolUse Timing Hook (All Sessions)

**Script:** `observe-tool-pre.sh`
**Trigger:** Before every Bash, Write, Edit, and Read tool invocation
**Registration:**
- **Main session:** Registered in `.claude/settings.json` with per-tool matchers (Bash, Write, Edit, Read).
- **All agents with `observe-tool.sh`:** Registered in agent frontmatter with the same per-tool matchers (Engineer, Tester, Simulator, Architect, PM, Designer).

**Behavior (YOK-1069, YOK-1082):**
1. Buffers stdin and extracts `tool_use_id` from the hook JSON payload.
2. Emits a lightweight `ToolCallStarted` event when `tool_use_id` is present.
3. Includes `tool_use_id`, `tool_name`, and `session_id` in the started-row envelope.
4. The PostToolUse hook (`observe-tool.sh`) reads the corresponding `ToolCallStarted` row to compute `duration_ms`.

**Always exits 0.** This is a data-collection hook with no blocking behavior. Falls back gracefully when `python3` is unavailable or started-row insertion fails.

## PostToolUse Hook (Main Session -- sqlite3 Error Detection)

**Script:** `sqlite3-error-hook.sh`
**Trigger:** After every Bash tool invocation in the main session
**Registration:** `.claude/settings.json` PostToolUse with `matcher: "Bash"`

**Behavior:**
1. **Stray-DB detection (YOK-667/YOK-669/YOK-1193):** After every Bash command, checks if a repo-root `yoke.db` exists (a symptom of the canonical DB path not being resolved). Zero-byte strays are logged to `yoke/ouroboros/stray-db-creation.log`, auto-removed, and now inject a hard-stop correction into agent context. Non-empty strays are logged and also inject a hard-stop correction, but are not auto-deleted.
2. **sqlite failure injection:** Parses the hook JSON for the command text and tool response. If the command contained `sqlite3` and the response includes a nonzero exit code, or if a Python command produced a `sqlite3.*Error` traceback, injects a hard correction message into the agent's context via `additionalContext`:
   > "HARD STOP: sqlite3 query FAILED (exit code N). Do NOT draw conclusions from a failed query. A failed query means the SQL was wrong or the DB state is unexpected -- it does NOT mean 'no results' or 'empty table'. Fix the query and re-run before proceeding."
3. **Row-count collapse detection (YOK-1296):** After DDL-like commands (`ALTER TABLE`, `DROP TABLE`, `CREATE TABLE`, `PRAGMA foreign_keys`, bulk `DELETE FROM`, `.restore`, `.import`), re-counts rows in critical tables (`items`, `epic_tasks`, `events`, `epic_progress_notes`, `qa_runs`) against a session-scoped baseline. On first DDL invocation per session, snapshots current counts to `$TMPDIR/yoke-row-baselines/baseline-{session_id}.json`. On subsequent DDL invocations, compares current counts to the baseline. Triggers a critical alarm if any table drops by >50% or collapses to 0-1 rows from a baseline of >10. Alarm injects `additionalContext` with table name, baseline/current counts, and recovery guidance (`backup-db.sh latest`). It also emits a FATAL-severity `DataLossDetected` event via `emit-event.sh` (best-effort). The baseline is never refreshed after a collapse — collapsed counts must not silently become the new baseline. Normal (non-DDL) Bash commands skip this check entirely for performance.

**Always exits 0** (PostToolUse hooks cannot block). The correction is injected as context, not as a denial.

## PreToolUse Lint Hooks (All Sessions)

Defined in `.claude/settings.json` and active for all sessions (main session + all subagents).

### lint-sqlite-cmd.sh (PreToolUse / Bash)

**Script:** `lint-sqlite-cmd.sh`
**Trigger:** Before every Bash tool invocation
**Behavior:** Blocks commands that violate Yoke coding conventions. The checks are grouped by category:

**Preprocessing:**
- **Heredoc stripping (YOK-491):** Before applying most checks, heredoc bodies (`<<EOF ... EOF`, `<<'EOF'`, `<<"EOF"`, `<<-EOF`) are stripped from the command. This prevents false positives from prose, examples, or non-shell code that appears inside heredocs. Executed Python payloads are inspected first so `sqlite3.connect(... "yoke.db" ...)` cannot hide inside a heredoc body.
- **Quoted-string stripping (YOK-919):** Interiors of single-quoted and double-quoted strings are stripped before pattern matching. This prevents false positives from example text, comments, or string literals that happen to contain blocked patterns.

**Checks:**
1. **Direct sqlite3 invocation (Check 1, YOK-273)** -- must use `yoke-db.sh` instead. Also blocks executed Python `sqlite3.connect(...)` calls when the snippet hardcodes a Yoke DB path such as `yoke.db`. Allowlisted exceptions for hook scripts and other approved contexts (YOK-374).
2. **Pipe-to-shell with sqlite3 in quoted content (Check 1a, YOK-919)** -- catches `echo '... sqlite3 ...' | sh` patterns that survive heredoc/quote stripping.
3. **Dangerous SQL operators (Check 2):**
   - **`!=` operator (Check 2a)** -- must use `<>` (zsh histexpand converts `!=` to `\!=` which sqlite3 rejects)
   - **Escaped comparison operators (Check 2b)** (`\>=`, `\<=`, `\>`, `\<`) -- indicates shell quoting issues
4. **Direct calls to guarded scripts (Check 3, YOK-299)** -- scripts that must be called through their wrapper (e.g., `backlog-registry.sh` via `yoke-db.sh items`, `merge-worktree.sh` via `done-transition.sh`). Bypass: `# lint:no-guard-check`.
5. **BSD-incompatible awk negation (Check 4, YOK-352)** -- `!var` patterns that fail on macOS awk. Use `var==0` instead.
6. **`claude` CLI invocation (Check 5, YOK-367)** -- nested Claude Code sessions crash the parent.
7. **`gh issue`/`gh pr` without `-R` flag (Check 6, YOK-680)** -- cross-project items need explicit repo targeting. Bypass: `# lint:no-repo-flag`.
8. **Git commit with conflict markers (Check 7, YOK-701)** -- blocks `git commit`/`git add` when Yoke-managed files contain conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
9. **Wrong SQL column names (Check 8, YOK-870)** -- static blocklist of commonly confused column names per table (e.g., `item_id` instead of `epic_id` in `epic_tasks`, `capability` instead of `type` in `project_capabilities`). Includes entries for `project_capabilities` (`capability`, `name`, `capability_type` -> use `type`) and `projects` table columns. Bypass: `# lint:no-column-check`.
10. **Dynamic schema validation via PRAGMA table_info (Check 8b, YOK-932)** -- supplements the static blocklist. For each table referenced in SQL, queries the actual DB schema and validates column names against `PRAGMA table_info`. Catches typos and drift that the static list does not cover. Falls back to static blocklist only if the DB is unavailable or `python3` cannot connect.
11. **Direct `status=done` writes (Check 9, YOK-950)** -- setting status to `done` must go through `done-transition.sh` ceremony (QA done-gate check). Bypass: `# lint:no-done-check`.
12. **Direct `yoke-db.sh qa` browser_substrate run-add (Check 10, YOK-1014)** -- browser QA runs must come from `browser-run-scenario.sh`, not direct `yoke-db.sh qa` calls. Bypass: `# lint:no-browser-run-check`.
13. **DDL in `yoke-db.sh query` (Check 11, YOK-1026)** -- schema changes (`ALTER TABLE`, `CREATE TABLE`, `DROP TABLE`) need a dedicated migration script with backup + verification. Bypass: `# lint:no-ddl-check`.
**Guarded script safe-command awareness (YOK-491):** When a guarded script name appears as an argument to a read-only or VCS command (`grep`, `cat`, `git`, `diff`, `ls`, etc.), it is treated as a file reference rather than an invocation and is not blocked. The check splits commands on compound operators (`;&|\n`, `$(`) and inspects each segment independently.

### lint-event-registry.sh (PreToolUse / Bash)

**Script:** `lint-event-registry.sh`
**Trigger:** Before every Bash tool invocation
**Behavior:** Validates `emit-event.sh` event names against the `event_registry` table. Three outcomes:

1. **Registered (active):** Allow (exit 0, no output). The event name exists in the registry with `status='active'`.
2. **Registered (deprecated):** Allow (exit 0), warning to stderr suggesting the event is deprecated and should be migrated.
3. **Not registered:** Deny (JSON to stdout with `permissionDecision: "deny"`). The deny message includes the `yoke-db.sh events registry add` command needed to register the event.

**Graceful degradation:** If the `event_registry` table does not exist (e.g., migration not yet run), exits 0 -- all events are allowed. Same behavior if `yoke.db` is not found.

**Scope limitation:** Only validates direct `emit-event.sh` calls in Bash commands. Events emitted indirectly (e.g., `emit-event.sh` called from within another script that the Bash command invokes) are not intercepted by this hook. The hook parses the Bash command text from the PreToolUse JSON payload and looks for `emit-event.sh` followed by `--name`.

### lint-main-commit.sh (PreToolUse / Bash)

**Script:** `lint-main-commit.sh`
**Trigger:** Before every Bash tool invocation (main session only -- registered in `.claude/settings.json`)
**Behavior:** Enforces the worktree discipline rule: "NEVER write implementation code on main." Blocks `git commit` on the `main` branch when:
- The current branch is `main` (or `master`)
- Open worktree-backed items exist in the DB
- Staged files include at least one file NOT on the bookkeeping allowlist

**Bookkeeping allowlist** (commits on main that are always OK):
- `yoke/ouroboros/**` -- health reports, wrapups (gitignored since YOK-1157)
- `yoke/flows.md` -- generated flows view
- `yoke/designs/**` -- generated design views (gitignored since YOK-1157)
- `yoke/projects/*/qa-artifacts/**` -- browser QA screenshots, reports (gitignored since YOK-1157)
- `AGENTS.md` -- shared project doctrine (`CLAUDE.md` is the compatibility symlink)
- `.claude/**` -- Claude config/skills/hooks (planning artifacts)

**Bypass:** Add `# lint:no-main-check` comment to the command.

**Denial event emission (YOK-1096):** When a commit is denied, emits a `ToolCallDenied` event to the `events` table with the denial reason for audit and Ouroboros analysis.

### lint-write-path.sh (PreToolUse / Write)

**Script:** `lint-write-path.sh`
**Trigger:** Before every Write tool invocation
**Behavior:** Two checks:

1. **`$$` in file paths** -- The Write tool treats `$$` literally (does not expand shell variables), which creates a mismatched filename. Use `mktemp` instead for temp files.
2. **`secrets.*` in `if:` conditions in workflow YAML (YOK-777)** -- GitHub Actions silently fails to parse workflows when `secrets.*` appears in `if:` conditions (zero jobs, no error). Only triggers for `.yml`/`.yaml` files under workflow-related paths (`.github/workflows/`, `templates/webapp/ops/`, `projects/*/ops/`). `secrets.*` in `env:`, `run:`, or `with:` blocks is safe and not flagged. See `yoke/docs/github-actions-gotchas.md` for the correct pattern.

### lint-workflow-secrets.sh (Deleted)

The standalone `lint-workflow-secrets.sh` script has been deleted (YOK-1265). Its functionality is fully covered by `lint-write-path.sh` Check 2, which runs as a PreToolUse hook on every Write operation.

## PreToolUse Hooks (Tester, Simulator, Boss)

**Trigger:** Before Write or Edit tool calls
**Behavior:** `echo 'BLOCKED: {Agent} cannot write/edit files' >&2 && exit 1`

Defense-in-depth. These agents already have Write/Edit excluded from their `tools` list and in their `disallowedTools`. The PreToolUse hook is the third layer -- catches any attempt at runtime. Registered in agent frontmatter for all three read-only agents: Tester, Simulator, and Boss.

## Session Startup Hook

**Script:** `harness-session-start.sh`
**Trigger:** On every user prompt submission (via `UserPromptSubmit` hook in `.claude/settings.json`)
**Behavior:**

1. **Fire-once guard:** Creates a marker file at `/tmp/yoke-session-{session_id}` on first invocation. Subsequent invocations within the same session detect the marker and exit silently (no output). The `session_id` is resolved from `$CLAUDE_SESSION_ID` (Claude Code runtime), falling back to JSON payload, then PID + timestamp.
2. **Session marker:** Writes session metadata for `observe-tool.sh` to read without querying the DB on every tool call.
5. **Yoke repo validation:** Checks for `yoke.db` (via `resolve-paths.sh`) at the resolved project root. Non-Yoke repos get no output (graceful skip).
6. **Non-main branch detection (YOK-857):** Warns when the main repo root is checked out to a non-main branch. Bookkeeping commits go to HEAD, so a stale branch checkout silently misdirects all bookkeeping.
7. **Dirty-state warning (YOK-268):** Warns when main has uncommitted changes from other sessions before work begins.
8. **DB integrity check:** Warns if `yoke.db` is missing or zero-bytes (does not block).
9. **Emit `AgentSessionStarted` event (YOK-407):** Calls `emit-event.sh` to emit a session lifecycle event to the `events` table. Includes session_id and environment context. Gracefully degrades if `emit-event.sh` or the events table is unavailable.
10. **Orientation block:** Emits a `## Yoke Orientation` Markdown block to stdout containing:
    - Recent commits (`git log --oneline -10`)
    - Current plan (`data/BOARD.md` content)
11. **Smart truncation:** When the plan exceeds `startup_plan_lines` (configurable in `yoke/config`, default: 300), the script parses board markers (`<!-- YOKE:BOARD:START/END -->`), drops the Done section first, then truncates remaining content to fit within the line budget. Falls back to simple line-count truncation if markers are absent or Python is unavailable.
12. **Graceful degradation:** Every external command is wrapped in `|| true`. If `git`, `python3`, or config reading fails, the script still exits 0 and emits whatever context it could gather. A completely failed run produces no output (silent skip) rather than an error.

The plain-text stdout injection mechanism works because Claude Code appends stdout from hooks that exit 0 to the agent's context automatically. No special formatting or API -- just `printf` to stdout.

## Session Shutdown Hook

**Script:** `harness-session-end.sh`
**Trigger:** On conversation shutdown (via `Stop` hook in `.claude/settings.json`)
**Behavior:**

1. Resolves the current Claude session ID through `hook-helpers.sh:get_session_id()`.
2. Resolves the canonical DB path through `resolve_yoke_db()`.
3. Exits 0 as a no-op when the session marker is absent, stale, already ended, or the DB is unavailable.
4. Calls `python3 -m runtime.harness.session_hooks` which delegates to `session-end --force` when a live session exists.

**Active-claim protection (YOK-1388):** `--force` bypasses the `CHAIN_PENDING` guard but does NOT bypass the active-claim guard. If the session still holds unreleased claims, `end_session()` rejects with `ACTIVE_CLAIM` and the hook treats it as a protected no-op (exit 0, no `SessionHookFailed`). Claims are released through the claim lifecycle (completed, handed_off, finalize-exit) or the stale-session reclaimer (`clean-stale-sessions`), not as a side-effect of session shutdown. For stranded claims, use the human-only `python3 -m runtime.api.service_client claim-release` CLI.

This hook is main-session-only. In agent frontmatter, `Stop` still auto-converts to `SubagentStop` and cannot distinguish clean completion from crash.

## Parallel Execution Safety

The hooks `on-agent-stop.sh`, `on-bash-complete.sh`, and `observe-tool.sh` use **worktree-scoping** to prevent cross-contamination during parallel execution. Before processing any dispatch chain, they compare `$CLAUDE_PROJECT_DIR` against the chain's `worktree_path` field and skip non-matching chains.

**Self-healing** (defense-in-depth):
1. The orchestrator (conduct or dispatch) always overrides hook statuses on normal completion
2. Re-entering through `/yoke conduct` detects and fixes stale "stopped" states from crashes

## Usher Executor Scripts

The Usher pipeline (`/yoke usher`) runs post-merge operations (board rebuild, GitHub sync, release notes) via executor scripts in `.agents/skills/yoke/usher/executors/`. These scripts run **outside the hook system** -- they are invoked directly by the Usher skill during its pipeline stages, not triggered by Claude Code hook events. They share the same DB access patterns (`yoke-db.sh`) and project-awareness as hooks, but their execution is orchestrated by the Usher skill rather than by Claude Code's hook infrastructure.

## Hook YAML Format

In agent frontmatter (nested matcher + hooks array):

```yaml
hooks:
  SubagentStop:
    - hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/on-agent-stop.sh"
  PostToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/on-bash-complete.sh"
    - hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/observe-tool.sh --agent engineer --hook-event PostToolUse"
  PostToolUseFailure:
    - hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/observe-tool.sh --agent engineer --hook-event PostToolUseFailure"
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/lint-sqlite-cmd.sh"
        - type: command
          command: ".agents/skills/yoke/scripts/observe-tool-pre.sh"
    - matcher: "Write"
      hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/observe-tool-pre.sh"
    - matcher: "Edit"
      hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/observe-tool-pre.sh"
    - matcher: "Read"
      hooks:
        - type: command
          command: ".agents/skills/yoke/scripts/observe-tool-pre.sh"
```

**PostToolUse composition:** Multiple entries under `PostToolUse:` are composed by Claude Code. The Engineer has both a Bash-specific `on-bash-complete.sh` (with `matcher: "Bash"`) and the global `observe-tool.sh --hook-event PostToolUse` (no matcher, fires on all tools). Both receive the hook JSON on stdin independently.

**PostToolUseFailure:** A separate hook type for failed tool calls. Uses the same `observe-tool.sh --hook-event PostToolUseFailure` script path, allowing the hook to skip duplicate failed emissions from the paired PostToolUse registration.

**Important:** `once: true` is skills-only -- not supported in agent frontmatter. In agent frontmatter, `Stop` auto-converts to `SubagentStop` -- can't distinguish normal completion from crash.

## Git Hooks

In addition to Claude Code hooks (above), Yoke uses native git hooks for repository-level protection.

### Pre-commit Hook: Working Tree Divergence Warning

**Script:** `.agents/skills/yoke/scripts/git-pre-commit.sh`
**Installation:** Symlinked to `.git/hooks/pre-commit` by `/yoke init` (step 4)
**Marker comment:** `# yoke-pre-commit -- installed by /yoke init`

**Purpose:** Warns when staged files have unstaged modifications. This catches a class of silent data loss where `git commit` records stale index content instead of the current working tree state. The concrete scenario: stage a file, modify it further, then commit -- git silently commits the pre-modification version.

**Behavior:**
1. Runs `git diff --name-only` to get files with unstaged changes
2. Runs `git diff --cached --name-only` to get staged files
3. Computes the intersection (files that are both staged AND modified since staging)
4. If intersection is non-empty, prints a warning to stderr listing the affected files
5. Always exits 0 -- this is a warning, never a block

**Warning output (to stderr):**
```
WARNING: These staged files have unstaged changes -- commit may not match working tree:
  <file1>
  <file2>

Run 'git add <file>' to stage latest content, or 'git commit --no-verify' to skip this check.
```

**Bypass:** `git commit --no-verify` suppresses the hook entirely.

**Worktree behavior:** Git worktrees share the main repo's `.git/hooks/` directory, so the hook fires automatically for commits in all worktrees. No per-worktree installation is needed.

**Collision detection:** `/yoke init` checks for the `yoke-pre-commit` marker before installing. If `.git/hooks/pre-commit` exists but does not contain the marker, init warns and skips -- it will not overwrite third-party hooks.

**Prerequisites check:** `check-prerequisites.sh` reports the hook status as a warning (not critical failure). Missing or non-Yoke hooks show a warning emoji, not a blocking error.

**Relationship to Claude Code hooks:** This is a native git hook, not a Claude Code hook. It runs at the git level and protects all commits regardless of whether they originate from Claude Code, a subagent, or direct terminal use. Claude Code hooks (PreToolUse, PostToolUse, etc.) operate at the tool-call level within Claude Code sessions.

## Lint Suppression Quick Reference (YOK-1075)

When developing or running tests, Bash lint hooks may block commands that are legitimate in a test context. This section centralizes the approved escape patterns. Each entry explains **what is blocked**, **why**, **the approved alternative**, and **when suppression is acceptable**.

### Decision Framework

There are two categories of lint blocks:

1. **Use a different command pattern.** The blocked command has a safer alternative that should be used instead. No suppression comment exists -- the alternative IS the fix.
2. **Use a suppression comment.** The blocked command is sometimes intentional. Append the suppression comment to the command to bypass the check.

### Quick Reference Table

| Blocked Pattern | Why Blocked | Approved Alternative | Suppression Comment | When Suppression Is Acceptable |
|---|---|---|---|---|
| Direct `sqlite3` invocation | Bypasses unified DB entry point; risks hardcoded paths, wrong CWD, silent empty-DB creation (YOK-273) | Use `yoke-db.sh query "..."` as the escape hatch. In test scripts, use `yoke-db.sh query` or test helpers that wrap it | **None** -- always use the wrapper | Never. There is no suppression comment for this check |
| `!=` in SQL | zsh histexpand converts `!=` to `\!=`, causing sqlite3 "unrecognized token" errors (YOK-280) | Use `<>` instead of `!=` in all SQL | **None** -- always use `<>` | Never. The operator is fundamentally unsafe in this shell context |
| Escaped operators (`\>=`, `\<=`, `\>`, `\<`) | Indicates shell quoting issues; backslash is passed to sqlite3 literally | Fix quoting so operators are unescaped | **None** | Never |
| Direct calls to guarded scripts (`backlog-registry.sh`, `merge-worktree.sh`, etc.) | Must be called through their wrappers (`yoke-db.sh items`, `done-transition.sh`) to ensure correct context (YOK-299) | Use the wrapper: `yoke-db.sh items add`, etc. | `# lint:no-guard-check` | When calling from usher merge flow (YOK-849), recovery scripts, or test scripts that need direct access to the underlying script |
| `gh issue`/`gh pr` without `-R` flag | Cross-project items need explicit repo targeting to avoid defaulting to the wrong repo (YOK-680) | Add `-R owner/repo` to the command | `# lint:no-repo-flag` | When the script intentionally targets multiple repos (e.g., migration scripts, doctor health checks). Must include explanatory text after the marker |
| Direct `status=done` writes | Setting status to `done` must go through `done-transition.sh` ceremony, which checks the QA done-gate (YOK-950) | Use `/yoke advance YOK-N done` or `done-transition.sh` | `# lint:no-done-check` | Only in test scripts that need to set up test state directly |
| ~~Direct retired completion-status writes~~ | *(YOK-1301: removed — the old completion token is no longer canonical)* | — | — | — |
| Direct `yoke-db.sh qa` with `browser_substrate` executor | Browser QA runs must come from `browser-run-scenario.sh`, not direct `yoke-db.sh qa` calls (YOK-1014) | Let `browser-run-scenario.sh` handle recording | `# lint:no-browser-run-check` | Only when called from within `browser-run-scenario.sh` itself |
| DDL in `yoke-db.sh query` (`ALTER TABLE`, `CREATE TABLE`, `DROP TABLE`) | Schema changes need a dedicated migration script with backup + verification (YOK-1026) | Write a dedicated migration script | `# lint:no-ddl-check` | After completing all migration safety steps (backup, verification, rollback plan) |
| Wrong SQL column names | Common column name mistakes cause silent empty results (YOK-870) | Use the correct column name (see AGENTS.md "Common column mistakes to avoid" section) | `# lint:no-column-check` | When the lint check produces a false positive (e.g., column name is valid but not in the static blocklist) |
| `git commit` on `main` with implementation code staged | Implementation code should be committed in worktrees, not on main (YOK-733) | Work in a worktree branch | `# lint:no-main-check` | Bookkeeping-only commits that include files outside the allowlist |
| BSD-incompatible `!var` in awk | `!var` fails on macOS BSD awk (YOK-352) | Use `var==0` instead of `!var` | **None** | Never. The pattern is not portable |
| `claude` CLI invocation | Nested Claude Code sessions crash the parent (YOK-367) | Use the Agent tool for subagent dispatch | **None** | Never |
| `$$` in Write tool file paths | Write tool treats `$$` literally, creating mismatched filenames | Use `mktemp` for temp files | **None** (blocked by `lint-write-path.sh`) | Never |

### Test Development Patterns

When writing test scripts under `.agents/skills/yoke/scripts/tests/`:

- **Direct DB access for setup/teardown:** Use `yoke-db.sh query "..."` -- never raw `sqlite3`. The `yoke-db.sh query` command accepts arbitrary SQL and handles DB path resolution.
- **Guarded script access:** If a test needs to call a guarded script directly (e.g., `schema-db.sh` for schema initialization testing), add `# lint:no-guard-check` to the command.
- **Status manipulation for test state:** Use `yoke-db.sh items update N status <status>` for most statuses. For `done`, add `# lint:no-done-check`.
- **Event capture without DB:** Set `YOKE_EVENTS_CAPTURE=1` and `YOKE_EVENTS_FILE=/path/to/capture.ndjson` to redirect `emit-event.sh` output to a file for assertion testing. See `test-events-helpers.sh` for the test harness API.
- **GitHub command mocking:** Tests mock `gh` commands with PATH-shadowing helper scripts. Never set `YOKE_DRY_RUN=1` in test suites.
