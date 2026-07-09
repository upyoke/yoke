# Error Handling, Dispatch Summary, and Notes

Reference file for halt conditions, subagent dispatch rules, and implementation notes. Referenced by the conduct phase files.

---

## Error Philosophy

**No such thing as "agent error."** Every halt condition below has a systemic root cause — truncated context, missing dispatch paths, stale task specs, exhausted retry budgets, or file size exceeding agent read limits (P-50). Before halting, query `yoke events tail --limit 20` to capture forensic context. When reporting the halt, frame the cause as what the SYSTEM should change, not what the agent did wrong. Documentation-as-enforcement fails under context pressure (P-26) — halts are a natural consequence of system limitations, not agent unreliability.

## Halt Conditions

Stop immediately and go to step 7 with HALTED status if any of these occur:

- Epic sync failure (see `dispatch-context.md` step 5f-epic.1)
- Same-worktree conflict (see `dispatch-context.md` step 5f-epic.3)
- Second FAIL on same item after retry
- **Simulator output gate exhausted** -- Simulator returned no parseable result after `MAX_SIMULATOR_REPROMPTS` retries. Safe default: HALT. See `simulation-gate.md` S6h.
- **Post-simulation auto-fix exhausted (see `simulation-autofix.md`)** -- auto-fix attempted first (Architect fix loop + amend cycle), worktrees preserved
- **Auto-fix exhausted without resolving gaps (see `simulation-autofix.md`)** -- Architect fix loop (3 iterations) and/or amend cycle (1 cycle) failed to produce a clean simulation. Worktrees preserved
- Main merge conflict unresolved after Engineer re-dispatch (see `dispatch-context.md` step 5h)
- Unrecoverable command/script failure

When halting, include remaining unprocessed items as "not started" and blocked items with their reasons in the final report.

---

## Subagent Dispatch Summary

| Phase | dispatch role | isolation | Parallelism | Purpose |
|-------|--------------|-----------|-------------|---------|
| Implementation | `yoke-engineer` | _(none)_ | Up to N in parallel — fan-out batch from `_task_ids` (S6c) routed via `engineer-tester-loop.md` Branch B | Write code, tests, docs in Yoke-managed worktree (path passed in prompt) |
| Validation | `yoke-tester` | _(none)_ | Up to N in parallel — mirrors Engineer batch | Review engineer's work. Read-only. |
| Integration sim | `yoke-simulator` | _(none)_ | Single | Trace cross-task gaps. Read-only. |
| Auto-fix (plan) | `yoke-architect` | _(none)_ | Single per-epic | Apply plan-level fixes to task specs after simulation gaps found. See `simulation-autofix.md`. |

Never dispatch other agent types (designer, boss, shepherd, etc.) from the conduct loop. The `yoke-architect` is only dispatched during the auto-fix flow (see `simulation-autofix.md`).

---

## Notes

- **Thin conduct principle.** The conduct loop orchestrates -- it never implements. All code, test, and doc work happens in Engineer/Tester subagents via the Agent tool. The conduct loop reads specs, runs status commands, launches subagents, and parses verdicts. Nothing else.
- **Parallel dispatch.** Engineers are dispatched in parallel (multiple Agent tool calls in the same response), then Testers are dispatched in parallel. The fan-out batch is sized by `_task_ids` from S6c (every chain head that survives same-worktree and dependency filtering) and the live entry is `engineer-tester-loop.md` Branch B, which consumes `dispatch-context-dispatch.md` (5g/5h) and `dispatch-context-prompts.md` (5i). Single-task batches degenerate to `engineer-tester-dispatch.md`. After all batch members reach a terminal task status, the integration simulation gate runs before post-pass processing. The conduct loop does not run done-transitions -- those are deferred to the merge/advance flow.
- **Retry budget is configurable and defaults to 5.** The conduct `--max-attempts` flag defaults to 5 total Engineer/Tester cycles per item. Users can override with `--max-attempts N` when they know a specific set of items needs a different retry budget. The retry set is processed separately from the primary set -- failed items are retried after successful items complete post-pass processing.
- **Item-type routing.** The conduct loop rejects issue items at entry and routes epic tasks through the epic fan-out path. Epic items use registered `yoke workflow-item epic-task update-status` only for non-pipeline task status writes; conduct dispatch/retry transitions keep the retained internal status pipeline because it owns dispatch attempts, history, and derive side effects. Dispatch-chain and unified worktree-creation calls are retained internal conduct boundaries, not normal product flow. Explicit architect/refine worktrees are preserved; only empty legacy task worktrees default to `YOK-{N}`. Task specs come from `yoke workflow-item epic-task body-get`.
- **Same-worktree protection (see `dispatch-context.md` step 5f-epic.3)** prevents two tasks from clobbering the same worktree. Tasks in different worktrees dispatch safely in parallel — this is the per-candidate filter applied by `entry-activation-resolution.md` S6c during fan-out enumeration. Uses DB queries instead of filesystem scans.
- **Epic auto-chaining (see `dispatch-context.md` step 5p).** After a PASS on an epic task, the conduct loop advances the dispatch chain.
- **Re-entry recovery.** On session crash/resume, the conduct loop classifies in-progress items by their DB status and worktree state. Items with Engineer commits go directly to Tester. Items in QA with no verdict get re-tested. This avoids re-running work that already completed.
- **Tester output gate escalation.** The Tester output gate tracks cumulative output failures per item and uses an escalating fallback chain to address context saturation from large inline diffs:
 1. **Retry 1** (`_tester_output_failures == 1`): Minimal prompt variant (no inline diff, file list only) with default model. This gives the Tester maximum context budget for file reads and test execution. See `dispatch-context.md` step 5i-minimal.
 2. **Retry 2** (`_tester_output_failures == 2`): Minimal prompt variant + `model: "opus"`.
 3. **Exhaustion** (`_tester_output_failures > MAX_TESTER_REPROMPTS`): Conduct direct verification -- run tests in the worktree directly and produce a synthetic verdict. See `dispatch-context.md` step 5i-conduct-verify. This is a documented exception to the Thin Conduct Principle, tracked via Ouroboros entry.

 This is distinct from a FAIL verdict -- a FAIL means the Tester worked correctly. The output gate handles cases where the Tester produced no parseable verdict at all (typically due to context saturation).
- **Simulator output gate.** When the Simulator returns no parseable result (neither `SIMULATION: CLEAN` nor `SIMULATION: GAPS FOUND`, and no fallback `CLEAN` or `GAPS FOUND` in text output), the conduct loop retries with escalated instructions demanding the full two-line verdict block (`SIMULATION:` then `EPIC: YOK-{N}`) as the first two lines of the response. After exhausting retries, the conduct loop HALTs. If a parseable verdict exists but the body omits or mismatches the `EPIC: YOK-{N}` attestation, `persist_simulation` exits 16 or 17 and conduct HALTs with the exact epic-identity diagnostic. This mirrors the Tester output gate but with a lower retry cap (1 vs 2) since simulation is expensive. Unlike the Tester gate, there is no conduct direct-verification fallback -- the conduct loop cannot simulate integration paths itself. In the auto-fix flow (`simulation-autofix.md`), unparseable Simulator output is treated as GAPS FOUND (staying in the fix loop) rather than HALT, while exit 16/17 identity failures HALT because they are not architectural gaps.
- **Conduct context stays small.** Each subagent invocation via Agent tool gets a fresh context window. The conduct loop sees only metadata and verdicts. Implementation details live in subagent context and are discarded on return. Parallel dispatch amplifies this benefit -- N items processed with the same conduct context overhead as one. Diffs >500 lines are not embedded inline -- the Tester reads them from the worktree. Epic auto-chaining resets task-level context between chain segments.
- **All state in the DB.** Epic task data (specs, statuses, reviews, chains, progress notes) is read from and written through registered `yoke workflow-item ...`, `yoke epic-tasks ...`, and `yoke items ...` surfaces wherever wrappers exist. Dispatch-chain maintenance and raw SQL assertions are retained internal/operator-debug boundaries. No filesystem status files.
- **The Engineer runs with `bypassPermissions`** so it can write code and run commands without approval prompts.
- **You do NOT intervene in the conduct loop.** Steps run autonomously until all items pass or a halt condition is reached.
- **Autonomous execution mode.** Every subagent return has a continuation marker. The conduct loop must immediately continue to the next step -- never pause or wait for user input.
