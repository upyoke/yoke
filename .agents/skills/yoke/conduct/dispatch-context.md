# Dispatch Context, Engineer/Tester Prompts, and Shared Steps

Referenced by the conduct phase files (`entry-activation.md`, `engineer-tester-loop.md`, `simulation-gate.md`). This file covers per-item context preparation (step 5f), prior attempt rehydration (step 5f-rehydrate), Engineer and Tester dispatch (steps 5g-5i), and shared utility steps (5m-5p).

**Inherited from router:** `MAX_TESTER_REPROMPTS` and all parsed arguments.

**Safe-read guidance:** This file and its children total ~1450 lines. **Do NOT read them end-to-end.** Use the section index below with the Read tool's `offset`/`limit` parameters to load only the section you need.

### Section Index

| Section | Location | Description |
|---|---|---|
| `5f. Prepare Per-Item Context` | this file | Item context preparation (issue + epic) |
| `5f-epic.1. Epic Sync Gate` | [dispatch-context-gates.md](dispatch-context-gates.md) | Epic sync pre-condition |
| `5f-epic.2. Epic Fan-Out Enumeration` | this file | Enumerate all dispatchable chain heads |
| `5f-epic.2a. Simulation Gap Gate` | [dispatch-context-gates.md](dispatch-context-gates.md) | Plan-phase simulation gap check |
| `5f-epic.3. Same-Worktree Protection` | [dispatch-context-gates.md](dispatch-context-gates.md) | Per-candidate dispatch guard |
| `5f-epic.4. Verify Dependencies` | [dispatch-context-gates.md](dispatch-context-gates.md) | Dependency and interface contract check |
| `5f-project` | [dispatch-context-project.md](dispatch-context-project.md) | Project context injection for every project-owned item |
| `5f-project-ephemeral` | [dispatch-context-gates.md](dispatch-context-gates.md) | Ephemeral environment lifecycle (E1-E5) |
| `5f-rehydrate` | [dispatch-context-rehydrate.md](dispatch-context-rehydrate.md) | Prior attempt rehydration for retries |
| `5g. Parallel Engineer Dispatch` | [dispatch-context-dispatch.md](dispatch-context-dispatch.md) | Engineer dispatch orchestration |
| `5g. Engineer Prompt Template` | [dispatch-context-prompts.md](dispatch-context-prompts.md) | Engineer prompt template |
| `5g Post-Return Submission Gates` | [dispatch-context-gates.md](dispatch-context-gates.md) | Submission gate, dirty-exit, rescue sweep |
| `5h. Main Merge Before Tester` | [dispatch-context-dispatch.md](dispatch-context-dispatch.md) | Pre-Tester main merge |
| `5i. Tester Dispatch` | [dispatch-context-prompts.md](dispatch-context-prompts.md) | Tester prompt templates and diff preparation |
| `5i-minimal` | [dispatch-context-prompts.md](dispatch-context-prompts.md) | Minimal Tester prompt (no inline diff) |
| `5i-conduct-verify` | [dispatch-context-gates.md](dispatch-context-gates.md) | Conduct direct verification fallback |
| `5m. Ouroboros Reflection Capture` | [dispatch-context-artifacts.md](dispatch-context-artifacts.md) | Post-subagent reflection capture |
| `5n. Tester Artifact Commit` | [dispatch-context-artifacts.md](dispatch-context-artifacts.md) | Commit Tester artifacts |
| `Epic-Task QA Lifecycle` | [dispatch-context-artifacts.md](dispatch-context-artifacts.md) | QA requirement seeding for epic tasks |
| `5o. Advance Status After PASS` | [dispatch-context-dispatch.md](dispatch-context-dispatch.md) | Post-PASS status advancement |
| `5p. Epic Auto-Chaining` | [dispatch-context-dispatch.md](dispatch-context-dispatch.md) | Auto-chain to next task in dispatch chain |

---

## 5f. Prepare Per-Item Context

Prepare the item's dispatch context (DB reads only).

### 5f-issue. Issue Item Preparation

#### 5f-issue.1. Load Spec

Fetch the item spec from DB (source of truth — structured field, not the full body):
```bash
_spec=$(yoke items get "${_id}" spec)
```

#### 5f-issue.2. Build Context Block

```
Issue: YOK-{_id}
Title: {_title}
GitHub Issue: {github_issue from DB}
Branch: YOK-{_id}
Worktree path: {_worktree_path}
Main repo root: {MAIN_ROOT}
Data directory: {MAIN_ROOT}/data (config and generated views live here)
Mode: Standalone issue (no epic, no task files)
Yoke DB: Postgres authority is selected by the backend; use `yoke <subcommand>` or `yoke db read --format lines ...`

File routing:
 Code, tests, task files -> Worktree root: {_worktree_path}
 Backlog items, board, QA data -> Main repo root: {MAIN_ROOT}
```

Run **5f-project** (see below) to append context for any project-owned item.

Store `_spec`, `_worktree_path`, and the context block for this item.

---

### 5f-epic. Epic Item Preparation

#### 5f-epic.1. Epic Sync Gate

Set the epic identifier (for epics, the item's own ID is the `epic_id` in `epic_tasks`):
```bash
_epic_id="${_id}"
```

Then run the **Epic Sync Gate** in [dispatch-context-gates.md](dispatch-context-gates.md) to ensure the epic is synced to GitHub. Auto-sync may update the connected Postgres authority, but git staging must still exclude generated views. If legacy root DB files appear in `data/`, stop and investigate.

Auto-sync's lifecycle target is status implementing; route it through the Yoke advance skill so orchestration, gates, and claim lifecycle run.

#### 5f-epic.2. Epic Fan-Out Enumeration

Resolve every dispatchable chain head in the epic, following the same fan-out contract as `entry-activation-resolution.md` S6c:

1. Read all dispatch chains for this epic:
 ```bash
 yoke workflow-item epic-dispatch-chain list --epic "$_epic_id"
 ```

2. For each dispatch chain, find the next dispatchable task:
 - Read `current_task` and its status from `epic_tasks`:
 ```bash
 yoke workflow-item epic-task get --epic "$_epic_id" --task-num "{current_task}"
 ```
 - If `current_task` status is `implementing` or `reviewing-implementation`: status alone is **not** a busy verdict. Call the shared freshness evaluator `yoke_core.domain.chain_head_freshness.evaluate_chain_head_freshness(epic_id, task_num, current_session_id)` — the same surface S6c in [entry-activation-resolution.md](entry-activation-resolution.md) calls, so this mirror cannot drift. The evaluator consults the parent claim, the prior session's `harness_sessions.last_heartbeat`, and the task's `epic_tasks.last_activity_at` (first-class task-freshness state stamped by every epic-task mutation; the events ledger is telemetry-only) against the chain-head freshness window (`chain_head_freshness_window_s`, default 60s). Branch on `decision.status`: `resumable` → treat the head as a **candidate** (the Engineer/Tester loop reaches `5f-rehydrate` and the resumed Engineer sees prior progress notes plus tester reviews; committed engineer work is not redone); `busy` → mark this chain busy and continue to the next chain; `blocked` → another live session holds the parent epic claim — record the blocker (see `decision.evidence.holder_session_id`) and continue.
 - If `current_task` status is `done` or `reviewed-implementation`: advance `current_index` to find the next task in the `queue`
 - If the next task's status is `planned`: this is a candidate; capture `_task_id`, `_worktree_branch`, and `_worktree_path`
 - If the next task is `blocked`: record the blocker and continue

3. For each candidate, run the same-worktree and dependency filters from `dispatch-context-gates.md` as per-candidate checks. Exclude only the blocked candidate; do not hold independent chains.
4. Surviving candidates become `_task_ids` (newline-separated). Also store each candidate's lane as `_worktree_branch_${_task_id}` and `_worktree_path_${_task_id}`.
5. If `_task_ids` is empty:
 - All tasks completed: Report item as fully complete.
 - Tasks in progress: report busy heads and wait for those tasks or re-enter from another tab.
 - Tasks blocked: report blockers and unmet dependencies.

#### 5f-epic.2a. Simulation Gap Gate

Run the **Simulation Gap Gate** in [dispatch-context-gates.md](dispatch-context-gates.md).

#### 5f-epic.3. Same-Worktree Dispatch Protection

Run the **Same-Worktree Dispatch Protection** in [dispatch-context-gates.md](dispatch-context-gates.md).

#### 5f-epic.4. Verify Dependencies and Interface Contracts

Run the **Verify Dependencies and Interface Contracts** gate in [dispatch-context-gates.md](dispatch-context-gates.md).

#### 5f-epic.5. Load Spec and Resolve Worktree

Read the task body from DB:
```bash
_body=$(yoke workflow-item epic-task body-get --epic "$_epic_id" --task-num "$_task_id")
```

Resolve the worktree path from the dispatch chain:
```bash
_chain_row=$(yoke workflow-item epic-dispatch-chain get --epic "$_epic_id" --worktree "$_worktree_branch")
```
Parse `worktree_path` from the chain row. Fallback: resolve the project-specific repo root and compute the path there:

```bash
# Fallback: resolve project-aware repo root for worktree path
_item_project=$(yoke items get "${_id}" project)
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 _project_root=$(yoke projects get --project "$_item_project" --field repo_path)
else
 _project_root="${MAIN_ROOT}"
fi
_slug=$(echo "$_worktree_branch" | sed 's|/|-|g')
_worktree_path="${_project_root}/.worktrees/${_slug}"
```

This ensures every project, including Yoke, resolves through the same registered repo root instead of assuming `MAIN_ROOT`.

Defense-in-depth: persist all three worktree fields to `epic_tasks`. This ensures that even if the activation step in `entry-activation-resolution.md` S6f is bypassed during re-entry recovery, the context preparation step writes all three fields. Since `metadata-update` is idempotent, redundant writes are harmless.

```bash
# Defense-in-depth: persist all three resolved dispatch-chain fields to epic_tasks.
# Preserve architect/refine per-task worktrees; do not collapse epic tasks to YOK-${_id}.
yoke workflow-item epic-task metadata-update \
  --epic "$_epic_id" --task-num "$_task_id" \
  --fields-json "{\"worktree\":\"${_worktree_branch}\",\"branch\":\"${_worktree_branch}\",\"worktree_path\":\"${_worktree_path}\"}"
```

#### 5f-epic.6. Build Context Block

```
Epic: {_epic_id}
Task ID: {_task_id} (local plan-order ID)
GitHub Issue: {github_issue from epic_tasks table}
Worktree path: {_worktree_path}
Main repo root: {MAIN_ROOT}
Data directory: {MAIN_ROOT}/data (config and generated views live here)
Yoke DB: Postgres authority is selected by the backend; use `yoke <subcommand>` or `yoke db read --format lines ...`

Progress notes: write via `yoke workflow-item epic-progress-note append`.
Reviews: Written by Tester via yoke workflow-item epic-task review-insert

File routing:
 Code, tests, task files -> Worktree root: {_worktree_path}
 Backlog items, board -> Main repo root: {MAIN_ROOT}
```

Run **5f-project** (see below) to append context for any project-owned item.

Store `_spec`, `_worktree_path`, and the context block for this item.

---

### 5f-project. Project Context Injection (shared sub-step)

<!-- Extracted to dispatch-context-project.md -->
See [dispatch-context-project.md](dispatch-context-project.md) for the full project context injection protocol: project query, `context_routing` always + topic assembly, test command validation, ephemeral URL query, and context block construction.

Independently of whether `5f-project` applies, run
**5f-project-ephemeral** in
[dispatch-context-ephemeral.md](dispatch-context-ephemeral.md) for any
non-empty project with the `ephemeral-env` capability.

---

## 5f-rehydrate. Prior Attempt Rehydration (shared sub-step)

<!-- Extracted to dispatch-context-rehydrate.md -->
See [dispatch-context-rehydrate.md](dispatch-context-rehydrate.md) for the full rehydration protocol: querying prior progress notes and tester reviews, assembling the rehydration block, and size guard truncation.

---

## 5g–5p. Engineer Dispatch, Main Merge, Tester, Post-PASS, Auto-Chaining

<!-- Extracted to dispatch-context-dispatch.md -->
See [dispatch-context-dispatch.md](dispatch-context-dispatch.md) for: Engineer dispatch orchestration (5g: baselines, branch-ahead detection, rehydration, engineer prompt, post-return), main merge (5h), Tester dispatch reference (5i), post-PASS status advancement (5o), and epic auto-chaining (5p).

---

## Child Files

Sections extracted from this file for size management:

- **[dispatch-context-project.md](dispatch-context-project.md)** — 5f-project: Project context injection for every project-owned item: project query, `context_routing` always + topic, test command validation, ephemeral URL, context block construction.

- **[dispatch-context-rehydrate.md](dispatch-context-rehydrate.md)** — 5f-rehydrate: Prior attempt rehydration: progress note + tester review queries, block assembly, size guard.

- **[dispatch-context-dispatch.md](dispatch-context-dispatch.md)** — 5g–5p: Engineer dispatch (baselines, branch-ahead, rehydration, post-return), main merge (5h), Tester reference (5i), post-PASS advancement (5o), epic auto-chaining (5p).

- **[dispatch-context-gates.md](dispatch-context-gates.md)** — Gates, pre-conditions, and validation steps: Epic Sync Gate, Simulation Gap Gate, Same-Worktree Protection, Dependency Verification, Ephemeral Environment Lifecycle (E1-E5), Post-Return Submission Gates, Conduct Direct Verification Fallback.

- **[dispatch-context-prompts.md](dispatch-context-prompts.md)** — Prompt templates and LLM call specs: Engineer Prompt Template, Tester Dispatch (diff preparation, epic/issue prompt templates), Minimal Tester Prompt, post-Tester cleanup.

- **[dispatch-context-artifacts.md](dispatch-context-artifacts.md)** — Artifact formats, output capture, and QA lifecycle: Ouroboros Reflection Capture, Tester Artifact Commit, Epic-Task QA Lifecycle, QA Quick Reference.
