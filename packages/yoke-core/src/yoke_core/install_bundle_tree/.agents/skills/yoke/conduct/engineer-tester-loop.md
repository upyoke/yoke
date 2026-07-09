# Conduct — Engineer/Tester Loop (S6g)

The Engineer/Tester execution phase of the conduct epic flow. Covers the Engineer dispatch, submission gate, Tester dispatch, verdict processing, retry logic, and auto-chaining to the next task. **Inherited from entry-activation:** `SCRIPT_DIR`, `MAIN_ROOT`, `_epic_id`, `N`, `_task_ids`, `_task_id`, `_worktree_path`, `_worktree_branch`, `TASK_BASELINE`, `_max_attempts`, `_no_chain`, context block.

---

#### S6g. Engineer/Tester Loop

This phase file is the **fan-out router**. It branches on the size of `_task_ids` (set by S6c) and selects the matching dispatch protocol. Both branches share the same closeout protocol applied per task.

```bash
_batch_size=$(printf '%s\n' "$_task_ids" | sed '/^$/d' | wc -l | tr -d ' ')
```

**Branch A — single-task batch (`_batch_size == 1`).** Use the existing single-task dispatch path. `_task_id` is the only entry in `_task_ids` and downstream prose reads it directly.

**Read and follow: `.agents/skills/yoke/conduct/engineer-tester-dispatch.md`**
Covers: loop initialization, branch-ahead detection (`_has_implementation`), attempt baseline, Engineer dispatch with submission gate, post-Engineer sweeps, review seeding, merge-main, and Tester dispatch with diff size-gating.

After Tester returns:

**Read and follow: `.agents/skills/yoke/conduct/engineer-tester-closeout.md`**
Covers: Tester artifact capture, ephemeral teardown, temp file cleanup, verdict parsing, the Tester output gate (escalating retry to opus + conduct direct verify), and verdict branching — PASS auto-chain to next task or `simulation-gate.md`, FAIL retry with `_attempt` increment, FAIL exhausted to `cleanup-report.md`.

**Branch B — multi-task fan-out batch (`_batch_size > 1`).** Use the parallel pathway. `N` / `_epic_id` remains the parent item throughout the batch; `_task_id` iterates the local epic task numbers from `_task_ids`. Per-task state vars carry the `_${_task_id}` suffix (e.g., `_worktree_path_${_task_id}`, `_worktree_branch_${_task_id}`, `ATTEMPT_BASELINE_${_task_id}`, `_has_implementation_${_task_id}`, `_attempt_${_task_id}`).

**Read and follow:** [`dispatch-context-dispatch.md`](dispatch-context-dispatch.md) sections **5g** (Parallel Engineer Dispatch — record per-task baselines, run branch-ahead detection per task, dispatch every Engineer in a single Agent-tool batch, then run the post-return submission gates per task) and **5h** (main-merge per task), then [`dispatch-context-prompts.md`](dispatch-context-prompts.md) section **5i** (Parallel Tester Dispatch — size-gate each task's diffs, dispatch every Tester in a single Agent-tool batch).

After all Testers return, run **engineer-tester-closeout.md** **per task** (verdict parsing, output-gate escalation, verdict branching). Before each closeout pass, hydrate the unsuffixed variables from the task's suffixed state:

```bash
for _task_id in $_task_ids; do
 _branch_var="_worktree_branch_${_task_id}"
 _path_var="_worktree_path_${_task_id}"
 _task_baseline_var="TASK_BASELINE_${_task_id}"
 _attempt_baseline_var="ATTEMPT_BASELINE_${_task_id}"
 _attempt_var="_attempt_${_task_id}"
 _tester_failures_var="_tester_output_failures_${_task_id}"
 _worktree_branch="${!_branch_var}"
 _worktree_path="${!_path_var}"
 TASK_BASELINE="${!_task_baseline_var}"
 ATTEMPT_BASELINE="${!_attempt_baseline_var}"
 _attempt="${!_attempt_var}"
 _tester_output_failures="${!_tester_failures_var}"
 # Then run engineer-tester-closeout.md for this task and write any updated
 # _attempt / _tester_output_failures values back to their suffixed variables.
done
```

PASS verdicts auto-chain via `dispatch-context.md` step 5p **per chain independently** — a chain whose head completes can auto-advance to the next dispatchable task without waiting for sibling chains. FAIL on a single batch member retries that task only; sibling tasks proceed independently. If one batch member's Tester times out or returns no verdict (after the output-gate exhausts), conduct halts that task and re-entry resumes it independently — sibling tasks that already passed remain at `reviewed-implementation`.

**Re-entry semantics.** A re-entry into `/yoke conduct` after a partial fan-out completion re-runs S6c. Tasks already at `implementing` or `reviewing-implementation` pass through the shared freshness evaluator (`yoke_core.domain.chain_head_freshness`) before being classified — fresh-heartbeat or recent-task-activity heads remain surfaced as busy, but stale heads whose parent claim is not actively held by another session route back into the candidate list via `resumable` and resume through `5f-rehydrate`. Newly dispatchable `planned` heads also enter the new batch. The parent epic does not advance to review/polish until every chain is terminal. This brings epic chain-head fan-out into parity with the issue path's same-session re-acquire semantics in `yoke_core.domain.worktree_preflight`.

**Per-task work-claim re-entry semantics.** Each Engineer/Tester dispatch in `engineer-tester-dispatch.md` acquires a `target_kind="epic_task"` claim (Step 3b for Engineer, Step 6b for Tester); the closeout in `engineer-tester-closeout.md` releases it. Three re-entry paths matter:

- **Same-session re-acquire** — the calling session already holds the active `epic_task` claim on `(epic_id, task_num)`. `yoke claims work acquire` is idempotent for same-session re-acquire (the dispatcher returns `result.already_owned=true` with `success=true`), so dispatch proceeds without a new row. The verify-claim-exists step confirms the row is still active before the Agent tool call.
- **Other-session-held** — a live sibling session legitimately holds the `epic_task` claim (e.g. concurrent operator on the same epic). The acquire returns `error.code="claim_conflict"` with the holder's session id; conduct routes through `chain_head_freshness.evaluate_chain_head_freshness` to classify the head as `busy` and skips this task in the current batch. No write under the other session's worktree happens; the dispatch never fires.
- **Stale-by-absent-session** — the prior holder's session ended (or its heartbeat aged past `session_stale_ttl_minutes` from machine config). The acquire auto-reclaims (`WorkReclaimed` event emitted) and conduct proceeds with a fresh `epic_task` row.

`chain_head_freshness` remains the diagnostic layer for stale claims; it does not author dispatch decisions, only classifies head state. Direct activation flows through `epic_task` claim acquisition.

---

#### Summary of Loop State Variables

Branch A (single-task) uses the unsuffixed forms below. Branch B (multi-task fan-out) uses the same names with a `_${_task_id}` suffix per batch member (e.g., `ATTEMPT_BASELINE_${_task_id}`, `_has_implementation_${_task_id}`, `_attempt_${_task_id}`). The per-task `TASK_BASELINE_${_task_id}` is set by entry-activation S6f's loop; S6f also publishes a singular `TASK_BASELINE` alias pinned to the primary task for downstream prose that has not been pluralized.

| Variable | Set by | Purpose |
|---|---|---|
| `_attempt` | dispatch | Current attempt number (1-based) |
| `_tester_output_failures` | closeout | Tester output gate escalation counter |
| `ATTEMPT_BASELINE` | dispatch | Commit SHA at attempt start |
| `TASK_BASELINE` | entry-activation (S6f) | Commit SHA at task start (preserved across retries) |
| `_has_implementation` | dispatch | Whether branch already had commits before loop |
| `_tester_feedback` | closeout | Tester's FAIL details for Engineer retry prompt |
| `_full_diff_file` | dispatch | Temp file: full branch diff for Tester |
| `_task_diff_file` | dispatch | Temp file: per-task diff (if size-gated) |
| `_attempt_diff_file` | dispatch | Temp file: per-attempt diff (if size-gated) |

---

#### Key References

- `dispatch-context.md` — step 5f-rehydrate (prior notes), step 5m (reflections), step 5n (artifact commit), step 5p (auto-chain), step 5i-minimal (minimal Tester prompt), step 5i-conduct-verify (direct verify). Use `offset`/`limit` to read only the relevant section.
- `entry-activation.md` S6f — re-read when restarting loop for next task in chain.
- `simulation-gate.md` (S6h) — read when all tasks reach terminal status.
- `cleanup-report.md` — read on HALTED (exhausted attempts) or `--no-chain` SUCCESS exit.

---

**Handoff:** When all tasks reach terminal status or the loop exits, read `.agents/skills/yoke/conduct/simulation-gate.md` to continue with the Integration Simulation Gate (S6h). On early exits (HALTED, `--no-chain`), go directly to `.agents/skills/yoke/conduct/cleanup-report.md`.
