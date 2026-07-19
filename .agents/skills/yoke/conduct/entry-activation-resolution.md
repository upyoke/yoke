# Conduct — Entry Activation Resolution (S6a–S6f)

Invoked from `entry-activation.md` S6. Covers Epic resolve, sync gate, fan-out enumeration of dispatchable tasks, same-worktree protection, dependency verification, and per-task activation with ephemeral environment lifecycle.

**Inherited:** `MAIN_ROOT`, `N`, `_epic_id`, `_task_ids`, `_task_id`, `_max_attempts`, `_no_chain`, `PROJECT`. `_task_ids` is a newline-separated list of dispatchable tasks for this invocation; `_task_id` is the primary entry — typically the first member of `_task_ids` and used by single-task downstream prose. Multi-task batches consume `_task_ids` plus per-task lane variables named `_worktree_branch_${_task_id}` and `_worktree_path_${_task_id}`.

---

#### S6a. Resolve Epic

```bash
# Convention: conduct operates on epic items; the item ID IS the epic ID.
# epic_tasks.epic_id is INTEGER NOT NULL — bare integer, never YOK-prefixed
# (mirrors shepherd/plan-handoff.md:23).
_epic_id=${N}
```

If `${N}` is empty the caller routed incorrectly; stop:
> /yoke conduct requires a numeric item ID.

#### S6b. Epic Sync Gate (auto-sync for unsynced epics)

An epic is "synced" when BOTH: (a) dispatch chains exist, AND (b) at least one `epic_tasks` row has a non-null `github_issue`.

```bash
_chains=$(yoke workflow-item epic-dispatch-chain list --epic "$_epic_id")
_synced_task_count=$(yoke db read --format lines "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='$_epic_id' AND github_issue IS NOT NULL AND github_issue <> ''")
```

**If already synced** (`_chains` non-empty AND `_synced_task_count > 0`): proceed to S6c.

**If NOT synced:**

1. Pre-check: `_task_count=$(yoke db read --format lines "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='$_epic_id'")`. If 0, stop: `No tasks found for YOK-{N}. Run '/yoke plan {_epic_id}' first.`

2. Auto-sync: Print `Epic YOK-{N} not yet synced to GitHub. Running sync automatically...` then:
 ```bash
 yoke items github-sync "$_epic_id"
 ```

3. Advance status to implementing: invoke the Yoke advance skill for `YOK-${N}` with target `implementing`.

4. Commit sync changes: Sync work is often DB-only — "nothing to commit" is valid. Never stage `.yoke/BOARD.md`. If legacy root DB files appear in `data/`, stop and investigate.
 ```bash
 git reset HEAD -- .yoke/BOARD.md 2>/dev/null || true
 git diff --cached --quiet || git commit -m "YOK-${N}: auto-sync — planned to implementing"
 ```
 If `git diff --cached --quiet` exits 0 (no tracked staged changes), that is fine — proceed.

5. Post-sync verification: re-check chains and `_synced_task_count`. If still empty/0:
 > Auto-sync failed for YOK-{N}. Investigate the sync failure before proceeding.

6. Print: `Auto-sync complete for YOK-{N}. Proceeding with dispatch.`

#### S6c. Epic Fan-Out Enumeration (multi-candidate dispatch)

This step enumerates **every** dispatchable head task across the epic's dispatch chains and produces a final list `_task_ids` for parallel activation. The companion gates (S6d same-worktree, S6e dependencies) are applied **per candidate** during enumeration so independent chains proceed when their siblings are excluded.

1. Read all dispatch chains through `yoke workflow-item epic-dispatch-chain list --epic "$_epic_id"`. `yoke epic-tasks list --epic "$_epic_id"` is the product read surface when chain ordering is not required.
2. For each chain, walk forward to the chain's current head:
 - `implementing` or `reviewing-implementation`: status alone is **not** a busy verdict. Call the shared freshness evaluator `yoke_core.domain.chain_head_freshness.evaluate_chain_head_freshness(epic_id, task_num, current_session_id)` to classify the head against the parent claim, the prior session's `harness_sessions.last_heartbeat`, and the task's `epic_tasks.last_activity_at` (first-class task-freshness state; per-task scoping is structural). The evaluator uses the chain-head freshness window (`chain_head_freshness_window_s`, default 60s) via `chain_head_freshness.resolve_freshness_window_s`. Branch on the returned `decision.status`:
   - `resumable` → treat the head as a **candidate** (capture `_task_id`, `_worktree_branch`, `_worktree_path` exactly as for `planned`). The Engineer/Tester loop reaches `5f-rehydrate` in `dispatch-context-rehydrate.md` and the prior progress notes plus tester reviews surface naturally to the resumed Engineer; committed engineer work on the branch is not redone.
   - `busy` → record the busy head task and continue to the next chain; busy chains do not contribute a candidate. Defer to SessionEnd-defense reactivation semantics.
   - `blocked` → another live session holds the parent epic claim (`decision.evidence.holder_session_id` carries the holder). Record the blocker and continue to the next chain.
 - `done` or `reviewed-implementation`: advance `current_index` past the completed task.
 - `planned`: this is a **candidate**. Capture its `_task_id`, `_worktree_branch` (chain's `worktree`), and `_worktree_path` (chain's `worktree_path`). Store those lane values as `_worktree_branch_${_task_id}` and `_worktree_path_${_task_id}` so later fan-out steps never reuse a sibling task's worktree.
 - `blocked`: skip — note the blocker and continue.
3. For each candidate, run the per-candidate filters (S6d, S6e):
 - **Same-worktree protection (S6d):** if another task in the same `_worktree_branch` is `implementing` or `reviewing-implementation`, **exclude** the candidate with explanation: `Excluded task {_task_id}: worktree {_worktree_branch} busy with task {other-id}.`
 - **Dependency verification (S6e):** for each entry in the candidate's `dependencies`, check status is `done` or `reviewed-implementation`. If any unmet, **exclude** with: `Excluded task {_task_id}: blocked by unmet dependencies: {blocker-ids}.`
4. Surviving candidates form `_task_ids` (newline-separated). Set `_task_id` to the first surviving candidate and hydrate `_worktree_branch` / `_worktree_path` from that task's suffixed variables so single-task downstream prose continues to work.
5. Re-entry semantics: tasks already at `implementing` / `reviewing-implementation` pass through the freshness evaluator in step 2 before being classified. Fresh-heartbeat or recent-task-event heads remain surfaced as busy and are NOT re-enumerated; stale heads whose parent claim is not actively held by another session route into the candidate list via `resumable` and resume through `5f-rehydrate` in `dispatch-context-rehydrate.md`. This closes the issue/epic asymmetry: the issue path's `yoke_core.domain.worktree_preflight` already recovers stale `implementing` via the `claim_work` primitive's same-session re-acquire plus `clean_stale_harness_sessions` sweep, and the epic chain-head fan-out now applies the matching freshness check.
6. If `_task_ids` is empty, report the terminal state for this invocation:
 - All chains complete (every chain's queue is fully `done`/`reviewed-implementation`): `All tasks in YOK-{N} are complete. Run '/yoke polish YOK-{N}' to finish the parent epic.`
 - Some chains busy (no exclusions, only `implementing`/`reviewing-implementation` heads): `YOK-{N} has tasks in progress: {list}. Wait for them to finish or open another tab.`
 - Some chains blocked (only excluded by dependency or same-worktree filters): `YOK-{N} has blocked tasks: {list with reasons}.`
 - Mixed (some busy, some excluded by filters): combine the busy and excluded summaries.

The `5f-epic.2` step in `dispatch-context.md` describes the same enumeration pattern at the dispatch-context layer; both surfaces speak in terms of multiple dispatchable head tasks rather than a single pick.

#### S6d. Same-Worktree Protection (per-candidate filter)

S6c applies same-worktree protection **per candidate** during enumeration. The exclusion is silent in the sense that other independent chains continue, but the per-candidate explanation surfaces in the S6c terminal report.

A candidate's worktree is busy when any other task in the same dispatch chain or sharing the same `_worktree_branch` is at `implementing` or `reviewing-implementation`. The same-worktree gate at `dispatch-context.md` step 5f-epic.3 is the canonical implementation; S6c calls it per candidate.

#### S6e. Verify Dependencies (per-candidate filter)

S6c applies dependency verification **per candidate**. For each entry in the candidate's `dependencies`, the candidate is excluded unless every dependency's status is `done` or `reviewed-implementation`. The exclusion lists unmet blocker IDs in the S6c terminal report. Independent chains whose dependencies are satisfied are not held up by other chains' blockers.

#### S6f. Activate Each Dispatchable Task

**Before the per-task loop:** activate any planned path claims for the epic, then provision every dispatchable chain worktree via the unified creator. This matches the single-worktree issue entry path: the caller flips path-claim rows from `state='planned'` to `state='active'`, and the creator remains the door-lock that refuses non-active claims. These are path-claim states, not item lifecycle statuses.

```bash
# Path-claim activation is a registered function-call surface.
yoke claims path activation-run --item "${_epic_id}"
_activation_exit=$?
if [ "$_activation_exit" -ne 0 ]; then
 echo "ERROR: path-claim activation failed for YOK-${N} (exit $_activation_exit). Investigate before re-running /yoke conduct."
 exit 1
fi

# Retained source-dev/internal boundary: unified lane worktree creation
# has no registered `yoke ...` wrapper yet.
python3 -m yoke_core.domain.worktree create "${_epic_id}" --project "${PROJECT}"
_creator_exit=$?
if [ "$_creator_exit" -ne 0 ]; then
 echo "ERROR: unified worktree creation failed for YOK-${N} (exit $_creator_exit). Investigate before re-running /yoke conduct."
 exit 1
fi
```

`--project "${PROJECT}"` routes the creator to the target project's local checkout mapping so cross-project epics (for example `project='external-webapp'`) materialize the worktrees under that project checkout, not Yoke's checkout. The creator resolves the epic's lane list from `epic_dispatch_chains`, runs the all-lane preflight (path-claim door-lock, dirty-main check, capacity, idempotency), and `git worktree add`s any missing lane. It is idempotent — lanes whose worktrees already exist on the expected branch are reported as preexisting and skipped. Failures (mismatched branches, dirty main, max_active_worktrees capacity) surface a structured error that names the failing lane before any per-task baseline runs.

Then loop over every task in `_task_ids` and run the per-task activation block. Each iteration hydrates `_worktree_branch` and `_worktree_path` from that task's suffixed lane variables, then writes the task's own status, baseline, and worktree fields. The same-worktree filter applied in S6c ensures no two iterations target the same `_worktree_branch`.

```bash
for _task_id in $_task_ids; do
 _branch_var="_worktree_branch_${_task_id}"
 _path_var="_worktree_path_${_task_id}"
 _worktree_branch="${!_branch_var}"
 _worktree_path="${!_path_var}"

 # 1. Load task spec
 _task_body=$(yoke workflow-item epic-task body-get --epic "$_epic_id" --task-num "$_task_id")

 # 2. Resolve worktree from dispatch chain
 _chain_row=$(yoke workflow-item epic-dispatch-chain get --epic "$_epic_id" --worktree "$_worktree_branch")
 # Resolve every project through the same project registry, including Yoke.
 _item_project=$(yoke items get "${N}" project)
 if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 _project_root=$(yoke projects get --project "$_item_project" --field repo_path)
 else
 _project_root="${MAIN_ROOT}"
 fi
 _slug=$(echo "$_worktree_branch" | sed 's|/|-|g')
 # Fallback worktree path: {_project_root}/.worktrees/{_slug}

 # 3. Record per-task baseline. The unified creator (above) has already
 # provisioned every lane; `git rev-parse` here is a verification step,
 # not a load-bearing creation. Use `declare` because bash performs
 # assignment-form recognition BEFORE parameter expansion, so the literal
 # `TASK_BASELINE_${_task_id}=value` form parses as a command, not an
 # assignment. Read via the main checkout's branch ref because the
 # per-task `epic_task` work-claim has not yet been acquired (Step 3b of
 # engineer-tester-dispatch.md does that) and `git -C "${_worktree_path}"`
 # against a lane worktree the orchestrator does not yet hold is blocked
 # by `lint_session_cwd`. Branches are repo-global; same SHA.
 declare "TASK_BASELINE_${_task_id}=$(git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}")"

 # 4a. Cross-Task Merge Plan — read `yoke items get YOK-${N} worktree_plan`
 # and look for a `## Cross-Task Merge Plan` section with an entry for
 # this task. For each predecessor named in the entry:
 #   - verify the predecessor task is `reviewed-implementation` or `done`
 #     via `yoke db read --format lines "SELECT status FROM
 #     epic_tasks WHERE epic_id=${_epic_id} AND task_num=<N>"`;
 #   - `git -C "${_worktree_path}" merge <predecessor-branch> --no-edit`.
 # Halt and route back to `/yoke refine` if any predecessor is unfinished
 # or any merge conflicts. Re-entry idempotent — `git merge` on an already-
 # merged commit is a fast-forward no-op; ALWAYS run the merge, never
 # skip based on a "did I already merge" check. Skip the entire step
 # when worktree_plan carries no `## Cross-Task Merge Plan` section.
 # Authored-format example (architect emits this in worktree_plan):
 #   ## Cross-Task Merge Plan
 #   Task 4 (cutover-base): before Engineer dispatch, merge into YOK-${N}-cutover-base:
 #     - YOK-${N}-substrate (task 1, must be reviewed-implementation+)
 #     - YOK-${N}-renderer (task 2, must be reviewed-implementation+)
 #   Task 7 (final-validation): merge YOK-${N}-cutover-base (task 6) before dispatch.

 # 4b. Update epic task status through the conduct pipeline wrapper.
 # `yoke workflow-item epic-task update-status` is the non-pipeline
 # wrapper and is not equivalent here because conduct needs the
 # dispatch_attempts/history/derive side effects.
 yoke conduct epic-task update-status --epic "$_epic_id" --task-num "$_task_id" \
  --status implementing --note "Dispatched by conduct (task fan-out)" --no-rebuild

 # 4c. Persist the resolved dispatch-chain worktree and branch on epic_tasks row.
 # Preserve architect/refine per-task worktrees; do not collapse epic tasks to YOK-${N}.
 yoke workflow-item epic-task metadata-update \
   --epic "$_epic_id" --task-num "$_task_id" \
   --fields-json "{\"branch\":\"${_worktree_branch}\",\"worktree_path\":\"${_worktree_path}\"}"

 # 4d. Refresh the dispatch chain row so telemetry and scheduler views see a
 # fresh (current_task, current_attempt, last_updated) triple. Step 4b bumped
 # epic_tasks.dispatch_attempts via the retained update_status pipeline; this
 # dispatch-chain refresh propagates that counter to
 # epic_dispatch_chains.current_attempt and stamps last_updated so downstream
 # readers see the live dispatch instead of yesterday's plan-sync.
 yoke workflow-item epic-dispatch-chain refresh-activation \
   --epic "$_epic_id" --worktree "${_worktree_branch}" --task-num "$_task_id"
done

# 4d. Persist worktree on parent backlog item (FR-6).
# Continue in the same harness session — no relaunch, no parent-stop, no scope envelope.
_task_id_primary=$(printf '%s\n' "$_task_ids" | sed '/^$/d' | head -n 1)
_primary_branch_var="_worktree_branch_${_task_id_primary}"
_primary_path_var="_worktree_path_${_task_id_primary}"
_primary_branch="${!_primary_branch_var}"
_primary_path="${!_primary_path_var}"
printf '%s\n' "YOK-${N} task ${_task_id_primary} worktree provisioned at ${_primary_path}; lane authority comes from each subagent's work-claim, not a scope envelope."

# 4e. Activation sanity gate — every task in _task_ids must now be at
# implementing/reviewing-implementation before the engineer dispatch
# proceeds. Catches the chain-advance skip pattern where the
# orchestrator advances the dispatch chain to a new task but drops the
# per-task activation block (status update / worktree fields / chain
# refresh) on the way in, leaving the task at status='planned' while
# the engineer writes
# commits to its branch.
for _task_id in $_task_ids; do
 _t_status=$(yoke db read --format lines \
   "SELECT status FROM epic_tasks WHERE epic_id=${_epic_id} AND task_num=${_task_id}")
 if [ "$_t_status" != "implementing" ] && [ "$_t_status" != "reviewing-implementation" ]; then
  echo "ERROR: YOK-${N} task ${_task_id} at status '${_t_status}', not activated. Re-run the S6f activation block (status update + metadata-update worktree/branch/worktree_path + dispatch-chain-refresh-activation) before dispatching engineer." >&2
  exit 1
 fi
done
```

The lane worktrees are now provisioned and `items.worktree` (branch slug) is set on the parent. The same harness session continues with the Engineer/Tester loop — no manual relaunch, no parent-stop, no `HarnessSessionEnded`. Each subagent dispatch (in `dispatch-context.md`) acquires its own `work_claim` on the parent epic, which is what `lint_session_cwd` reads to authorize writes under the dispatched lane. Multi-lane fan-out does not race a session envelope because no envelope exists; each lane stands on its own work-claim.

Build context block (same as `dispatch-context.md` 5f-epic.6):
```
Epic: {_epic_id}
Task ID: {_task_id} (local plan-order ID)
GitHub Issue: {github_issue from epic_tasks table}
Worktree path: {_worktree_path}
Main repo root: {MAIN_ROOT}
Yoke DB: Postgres authority is selected by the backend; use `yoke <subcommand>` for product flow; raw SQL is a retained operator-debug fallback only.

Progress notes: Write via yoke workflow-item epic-progress-note append
Reviews: Written by Tester via yoke workflow-item epic-task review-insert

File routing:
 Code, tests, task files -> Worktree root: {_worktree_path}
 Backlog items, board -> Main repo root: {MAIN_ROOT}
```

#### S6f-eph. Ephemeral Environment Lifecycle (E1-E3)

After context preparation, run `5f-project-ephemeral` (see
`dispatch-context.md`) for any non-empty project with the `ephemeral-env`
capability. It creates the DB record (E1), dispatches the capability's declared
GitHub-push or flow model (E2), and reads healthy status (E3). Resolved `_ephemeral_url` and `_env_id` carry
forward to Tester context and post-Tester teardown.

Check capability:
```bash
if ! yoke projects capability has --project "${_project}" --cap-type "ephemeral-env"; then
 if [ -n "${_project}" ]; then
 echo "Warning: project '${_project}' has no ephemeral-env capability — skipping ephemeral environment lifecycle."
 fi
fi
```

Skip entirely if the project is empty or lacks `ephemeral-env`. Only run on the
**first task dispatch** for a given worktree branch (check if `_env_id` is
already set).

Use `offset`/`limit` to read only the `5f-project-ephemeral` section of `dispatch-context.md` (~line 342).

---

**Continuation:** Resolution complete. The current harness session now holds the task work claim(s), and per-call target validation authorizes worktree-targeting calls through those claims. Continue directly into `.agents/skills/yoke/conduct/engineer-tester-loop.md`. When `_task_ids` carries more than one task, the loop routes through the parallel pathway in `dispatch-context-dispatch.md` and `dispatch-context-prompts.md` (sections 5g/5i); single-task batches stay on the existing `engineer-tester-dispatch.md` -> `engineer-tester-closeout.md` path.
