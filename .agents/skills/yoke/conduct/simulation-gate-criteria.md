# Conduct — Simulation Gate Criteria

Invoked from `simulation-gate.md` S6h after the skip check. Covers Simulator dispatch (standard and compressed modes), scope estimation, the Simulator output gate (auto-retry with escalating strategies), and simulation result persistence/verification.

**Inherited:** `SCRIPT_DIR`, `MAIN_ROOT`, `_epic_id`, `N`, `_worktree_path`, `_worktree_branch`, `_max_attempts`, `MAX_SIMULATOR_REPROMPTS`, `MAX_ARCHITECT_FIX_ITERATIONS`, `_project`, `_workspace`.

**Produces:** `_local_result` (`CLEAN` or `GAPS FOUND`) and `_verified_verdict` (after persistence).

---

### Gather Task List

```bash
_task_list=$(python3 -m yoke_core.cli.db_router query "SELECT task_num, title, status FROM epic_tasks WHERE epic_id='${_epic_id}' ORDER BY task_num")
_worktree_list=$(python3 -m yoke_core.cli.db_router query "
SELECT t.task_num, t.title,
       COALESCE(NULLIF(t.branch,''), NULLIF(t.worktree,''), c.worktree, '') AS branch,
       COALESCE(NULLIF(t.worktree_path,''), NULLIF(c.worktree_path,''), '') AS worktree_path
FROM epic_tasks t
LEFT JOIN epic_dispatch_chains c
  ON c.epic_id=t.epic_id
 AND c.worktree=COALESCE(NULLIF(t.branch,''), NULLIF(t.worktree,''), '')
WHERE t.epic_id='${_epic_id}'
ORDER BY t.task_num")
```

### Dispatch Mode Selection

Compressed two-phase mode is the default. Standard mode only when `sim_force_standard_integration=true` in config.

```bash
_force_standard=$(python3 -m yoke_core.domain.runtime_settings get sim_force_standard_integration false)
_sim_task_count=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='${_epic_id}'")
```

If `_force_standard` is `true`, set `_use_compressed=false`. Otherwise `_use_compressed=true`.

**Scope estimate (observability only — does not gate mode):**
```bash
_body_bytes=0 # sum wc -c of all task bodies
_review_bytes=0 # sum wc -c of all task reviews
_spec_bytes=$(yoke items get ${N} spec 2>/dev/null | wc -c)
_plan_bytes=$(yoke items get ${N} technical_plan 2>/dev/null | wc -c)
_diff_bytes=0 # sum wc -c of git diff --stat per distinct branch
_total_kb=$(( (_body_bytes + _review_bytes + _spec_bytes + _plan_bytes + _diff_bytes) / 1024 ))
```
Log: `[S6] Scope: {_sim_task_count} tasks, ~{_total_kb}KB → {standard|compressed}`

### Standard Dispatch (if `_use_compressed` is false)

**Dispatch:** descriptor `DispatchDescriptor(role="simulator")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `SIMULATION: CLEAN|GAPS FOUND`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Run integration simulation for epic {_epic_id} (YOK-{N}).
 Repository root: {MAIN_ROOT}
 Scripts directory: {MAIN_ROOT}/.agents/skills/yoke/scripts
 All tasks passed testing. Trace execution paths across tasks to find cross-task integration gaps.
 IMPORTANT: Your response MUST begin with the two-line verdict block — line 1 is SIMULATION: CLEAN or SIMULATION: GAPS FOUND, line 2 is EPIC: YOK-{N}. Persistence rejects bodies whose attested epic does not match YOK-{N} (exit 16) or that omit the EPIC line entirely (exit 17).
 Worktree-State Authority: a task's resolved worktree checkout is the authority for that task's actual code whether the item/epic has one worktree or many. Main is the base/integration target, not evidence of unmerged task state. Use the task's worktree_path / branch when verifying files; if no worktree path or prompt-supplied diff exists, report evidence missing instead of inspecting main as a substitute.
 Worktree authorities: {_worktree_list}
 Epic tasks: {_task_list}
```

### Compressed Dispatch (if `_use_compressed` is true default)

Assemble compressed context (interface contracts, shim re-export contracts,
file overlap matrix, dependency edges, worktree authorities, diff stats,
and commit-boundary evidence) using the same logic as `simulate/SKILL.md` step
3 compressed path, then dispatch with two-phase analysis protocol. For
shim-style modules, parse
the explicit `from yoke_core.board.X import (...)` blocks and include every
re-exported name, including public names and underscore-prefixed names such as
`_BLOCKS`. The shim import list is the source of truth; do not infer exports
from child module internals. When a task or epic AC contains discrete-commit,
separate-commit, or NFR-style commit-boundary language, include a bounded
parent-supplied `git log --oneline -- {file}` line for each affected file.
If no affected file can be discovered, include `commit evidence unavailable:
no affected file named` instead of silently dropping the audit requirement.
This prompt-supplied evidence is allowed; simulator-initiated `git log` or
`git blame` remains forbidden unless explicitly requested.

**Dispatch:** descriptor `DispatchDescriptor(role="simulator")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `SIMULATION: CLEAN|GAPS FOUND`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Run integration simulation for epic {_epic_id} (YOK-{N}).
 Repository root: {MAIN_ROOT}
 Scripts directory: {MAIN_ROOT}/.agents/skills/yoke/scripts

 ## Phase: INTEGRATION — COMPRESSED CONTEXT ({_sim_task_count} tasks)
 IMPORTANT: Your response MUST begin with the two-line verdict block — line 1 is SIMULATION: CLEAN or SIMULATION: GAPS FOUND, line 2 is EPIC: YOK-{N}. Persistence rejects bodies whose attested epic does not match YOK-{N} (exit 16) or that omit the EPIC line entirely (exit 17).
 Worktree-State Authority: a task's resolved worktree checkout is the authority for that task's actual code whether the item/epic has one worktree or many. Main is the base/integration target, not evidence of unmerged task state. Use the task's worktree_path / branch when verifying files; if no worktree path or prompt-supplied diff exists, report evidence missing instead of inspecting main as a substitute.

 ## Interface Contracts Per Task
 {extracted contracts per task}

 ## Shim Re-Export Contracts
 {module path, source import block, and every re-exported name from each
 shim import list, including underscore-prefixed names such as _BLOCKS}

 ## File Overlap Matrix
 {files touched by multiple tasks}

 ## Dependency Edges
 {task_num, title, dependencies per task}

 ## Worktree Authorities
 {_worktree_list}

 ## Diff Stats Per Branch
 {git diff --stat per branch}

 ## Commit-Boundary Evidence
 {task or AC identifier, affected file path, and one parent-supplied
 git log --oneline -- {file} line proving each discrete commit boundary;
 or commit evidence unavailable: no affected file named}

 ## Task Statuses
 {_task_list}

 ## TWO-PHASE ANALYSIS PROTOCOL
 ### Phase A — Bounded Preliminary Verdict (NO tool calls)
 Using ONLY the compressed context above, produce:
 1. Preliminary verdict: SIMULATION: CLEAN or SIMULATION: GAPS FOUND
 2. Up to 3 candidate gaps with severity, category, and brief description
 Do NOT use any tools during Phase A.

 ### Phase B — Selective Verification (max 5 file reads)
 Optionally read up to 5 files to verify or refute candidate gaps.
 Rules: only read files named in compressed context; use specific-file diffs only;
 upgrade/downgrade gap severities; produce final verdict and gap report.

 ## FORBIDDEN OPERATIONS
 - Broad git diff of entire branches (without -- {specific-file})
 - ls, find, or glob file enumeration of directories
 - Reading files not named in the compressed context
 - Git archaeology (git log, git blame) unless explicitly requested. Parent-supplied
   Commit-Boundary Evidence in this prompt is allowed evidence; do not run
   git log or git blame yourself.

 Produce your gap report. Use [CRITICAL], [WARNING], [NOTE] severity prefixes.
```

### Parse Local Result

After Simulator returns, emit `[CONTINUE] Simulator returned for YOK-{N}. Next: parse simulation result (S6h)` then:

- Capture reflections (see `dispatch-context.md` step 5m; use `offset`/`limit`).

```bash
_local_result=""
case "{simulator_output}" in
 *"SIMULATION: CLEAN"*) _local_result="CLEAN" ;;
 *"SIMULATION: GAPS FOUND"*) _local_result="GAPS FOUND" ;;
 *"CLEAN"*) _local_result="CLEAN" ;;
 *"GAPS FOUND"*) _local_result="GAPS FOUND" ;;
esac
```

If `_local_result` remains empty, enter the **Simulator output gate** below.

### Simulator Output Gate

Initialize `_simulator_output_failures=0` before the initial Simulator dispatch.

**Defensive `_epic_id` precondition (Layer 4).** Before any Simulator dispatch — including the initial dispatch and every retry tier below — assert that `_epic_id` is set and non-empty. A long-running parent session that has been compacted or had its shell variables clobbered can otherwise send a retry prompt with an empty epic field, producing a hallucinated body. **HALT** before invoking the simulator:

```bash
if [ -z "${_epic_id:-}" ]; then
 echo "[CRITICAL] _epic_id lost between dispatches — refusing retry. Halting simulator gate."
 # Go to cleanup-report.md with HALTED
fi
```

`simulation-gate-escalation.md` documents this HALT as the `_epic_id lost between dispatches` branch under the existing CRITICAL escalation tree. The check refuses dispatch, not just retry: if the initial dispatch is reached with no `_epic_id`, conduct halts before any simulator invocation.

When no parseable result is found:

1. **Increment `_simulator_output_failures`.**

2. **Classify failure mode:**
 - `context_exhaustion`: output ends mid-sentence, contains tool-call fragments without report structure, contains file exploration without `## Summary`/`## Paths Traced`, or is shorter than 500 characters.
 - `formatting_omission`: output has structured report content (`## Gaps Found`, `## Paths Traced`, `## Summary`) but is missing the `SIMULATION:` verdict line OR the `EPIC: YOK-{N}` attestation line.
 Log: `[S6h] Simulator output gate: failure mode = {context_exhaustion | formatting_omission}`

3. **If `_simulator_output_failures` <= `MAX_SIMULATOR_REPROMPTS` (2):**

 Re-assert the `_epic_id` precondition above before dispatching the retry. An empty `_epic_id` at retry time is the same CRITICAL halt as at initial dispatch.

 **3a. If `formatting_omission`:** Re-invoke with escalated instructions requiring the full two-line verdict block as the FIRST TWO LINES of the response — `SIMULATION: CLEAN` or `SIMULATION: GAPS FOUND` on line 1, then `EPIC: YOK-${_epic_id}` on line 2. Full task list included.

 **3b. If `context_exhaustion`:** Re-invoke with compressed context + two-phase protocol + aggressive constraints. Assemble compressed context bundle inline, including shim re-export contracts with public and underscore-prefixed names such as `_BLOCKS` whenever the compressed task/file context names a shim module, and Commit-Boundary Evidence for any discrete-commit/NFR-style AC named by the task or epic context:
 ```bash
 # Dependency edges
 _deps=$(python3 -m yoke_core.cli.db_router query "SELECT task_num, title, dependencies FROM epic_tasks WHERE epic_id='${_epic_id}' ORDER BY task_num")
 ```
 Add `## AGGRESSIVE RETRY CONSTRAINTS` section. The retry prompt MUST repeat the two-line verdict block requirement (`SIMULATION:` line then `EPIC: YOK-${_epic_id}` line). The prompt must also distinguish parent-supplied commit evidence from simulator-initiated git archaeology: supplied `git log --oneline -- {file}` lines are evidence, but the simulator must not run `git log` or `git blame` itself.

 **3c. Ultra-compressed no-tool fallback:** Assemble ultra-compressed context (overlap matrix + dependency edges + one-line task summaries only, plus shim re-export contracts when a candidate gap depends on a shim's exported symbols, plus any Commit-Boundary Evidence required to verify discrete-commit ACs):
 ```bash
 # Dependency edges (same as 3b)
 _deps=$(python3 -m yoke_core.cli.db_router query "SELECT task_num, title, dependencies FROM epic_tasks WHERE epic_id='${_epic_id}' ORDER BY task_num")
 ```
 Dispatch with hard NO-TOOL MANDATE. Two-line verdict block (`SIMULATION:` then `EPIC: YOK-${_epic_id}`) MUST be the first two lines. Maximum 3 gaps.

 Every retry prompt MUST carry Worktree-State Authority and the `_worktree_list`
 for single-worktree and multi-worktree epics. Retried simulation still verifies
 unmerged task state from the resolved worktree, never from main.

 After each re-invocation: capture reflections, re-parse `_local_result`. If found, use it.

4. **If `_simulator_output_failures` > `MAX_SIMULATOR_REPROMPTS`:** Log exhaustion, log Ouroboros entry, **HALT** — do NOT treat as CLEAN. **Go to `cleanup-report.md`** with `HALTED`.

### Persist and Verify

```bash
set +e
_verified_verdict=$(echo "{simulator_output}" | python3 -m yoke_core.domain.persist_simulation "${_epic_id}" "integration")
_persist_rc=$?
set -e
```

**If `_persist_rc` non-zero:** Map exit code to diagnostic and log Ouroboros entry. **Go to `cleanup-report.md`** with `HALTED`.

| Exit | Meaning | Operator-facing diagnostic |
|---|---|---|
| 10 | upsert failed | `[CRITICAL] persist_simulation upsert failed for YOK-${_epic_id} integration` |
| 11 | missing persisted row after upsert | `[CRITICAL] persist_simulation readback missing for YOK-${_epic_id} integration` |
| 12 | inconclusive verdict | `[CRITICAL] persist_simulation persisted an empty verdict for YOK-${_epic_id} integration` |
| 13 | parser mismatch (local vs persisted) | `[CRITICAL] persist_simulation parser mismatch for YOK-${_epic_id} integration` |
| 14 | no parseable verdict in body | `[CRITICAL] simulator output for YOK-${_epic_id} integration has no SIMULATION: verdict line` |
| 16 | wrong-epic body (CLI epic ≠ body epic) | `[CRITICAL] simulator returned body for wrong epic — CLI passed YOK-${_epic_id}, body attested a different epic. Check the captured simulator output for the offending EPIC: line.` |
| 17 | missing-epic body (no EPIC line, no heading fallback) | `[CRITICAL] simulator output for YOK-${_epic_id} integration has no EPIC: YOK-N attestation line and no legacy heading fallback. The two-line verdict block requirement was not met.` |

The `[CRITICAL]` prefix is required so `cleanup-report.md` surfaces the wrong-epic / missing-epic outcome explicitly to the operator. Exits 16 and 17 in particular must preserve the exact `persist_simulation` error text in the cleanup report because it names the CLI-passed epic and (for 16) the body-attested epic; do not replace it with a generic parser-failure line.

**If `_persist_rc` is 0:** Use `_verified_verdict` for all downstream branching. Set `_local_result="$_verified_verdict"`.

---

**Handoff:** `_local_result` and `_verified_verdict` are set. Read and follow `.agents/skills/yoke/conduct/simulation-gate-escalation.md` for result branching.
