---
name: conduct
description: "Single-item execution orchestrator for epic items. Starts from `planned`, resumes at `implementing` / `reviewing-implementation`, runs Engineer + Tester plus integration simulation, and hands the parent epic off at `reviewed-implementation` for `/yoke polish`."
argument-hint: "PREFIX-N [--max-attempts N] [--no-chain]"
---

# /yoke conduct PREFIX-N

Run a single backlog item through the Engineer/Tester loop (epic items only).

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Workflow binding gate

**Conduct is bound to the Epic workflow.** If the target item's
`workflow_id` is not `epic`, reject immediately:

```
Error: /yoke conduct is not the registered skill for workflow '{workflow_id}' on PREFIX-{N}.

Issue implementation routes through /yoke advance (main-session inline implementation).
Issue refinement routes through /yoke refine.
Issue polish routes through /yoke polish.

Run '/yoke advance PREFIX-{N} implementation' to begin issue implementation.
```

Check the workflow binding early (in S2 or before the status gate) and halt
before any worktree or status mutation.

## Phase map — read one file, at the phase it governs

**Do NOT read all files upfront.** Read each phase file only when you reach
that phase. This preserves context budget for the subagent dispatches that
consume the majority of a conduct session. Each phase file ends with an
explicit handoff to the next.

| Phase | You are here when | Read before acting |
|---|---|---|
| 0. Entry contract | The invocation just arrived | [`entry-gates.md`](entry-gates.md) |
| 1. Entry and activation | The three hard blocks passed | [`entry-activation.md`](entry-activation.md) (S1–S6f) |
| 2. Engineer/Tester loop | Activation completed (S6f done) | [`engineer-tester-loop.md`](engineer-tester-loop.md) (S6g) |
| 3. Simulation gate | Every task reached `reviewed-implementation` | [`simulation-gate.md`](simulation-gate.md) (S6h) |
| 4. Cleanup and report | Any exit path — SUCCESS, HALTED, `--no-chain` | [`cleanup-report.md`](cleanup-report.md) (6z, 6z-cleanup, 7) |
| — Output gate exhausted | A Tester or Simulator dispatch returned no parseable verdict | [`retry-budgets.md`](retry-budgets.md) |

Supplemental files a phase step may name — `dispatch-context.md`,
`simulation-autofix.md`, `error-handling.md` — and the map of which file
owns which conduct responsibility are in [`file-map.md`](file-map.md).
Read it when a step names one, not before.

## Autonomous Execution Mode

After every subagent returns, the conduct skill MUST immediately continue to the next step. Do not summarize, do not wait for user input. Each subagent return is a transition point, not a stopping point.

Worktree creation/activation is a pure filesystem + DB operation: active
`item_worktrees` lane rows are recorded, enabled path claims activate, and the
same harness session continues directly into the Engineer/Tester loop —
no manual relaunch, no parent-session stop, no claim handoff to a fresh session,
no scope envelope.

## Thin Conduct Principle

the conduct skill is an **orchestrator, not an implementor**. Its direct actions are strictly limited to:

- **Reading** backlog items, task specs, and subagent results
- **Running** state commands via registered `yoke ...` surfaces (`yoke items get`, `yoke lifecycle transition`, `yoke workflow-item epic-task update-status`) whenever wrappers are semantically equivalent; retained pipeline/internal calls must be labeled sharply
- **Launching** subagents via the Agent tool (Engineer, Tester, Simulator)
- **Parsing** verdicts and deciding next steps (retry, advance, halt)

the conduct skill MUST NOT:
- Read source code files to understand implementation
- Write or edit any code, tests, or documentation
- Run test suites or build commands directly
- Implement fixes or changes of any kind

All implementation and verification work happens inside subagents, which get fresh context and do not bloat the conduct skill's window. When a subagent returns, the conduct skill reads only the verdict and summary -- not the full implementation details.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent. Each Engineer and Tester dispatch starts with a cold context. The dispatch prompt must be self-contained for this dispatch — absolute paths, item metadata, current diff, test commands — not a restated session transcript. Missing a single path costs an entire subagent session.

**Codebase-reader naming travels through dispatch.** Assume future readers of the codebase will NOT have the ephemeral planning artifacts this conduct run is using. Engineer and Tester prompts must remind subagents that task specs are scaffolding, not naming source material: live names, comments, and current-state docs describe current function, purpose, mechanics, or domain role, never the work item, plan, phase, task, AC, branch, worktree, or batch that produced them.

**No such thing as "agent error."** When the Engineer fails or the Tester returns no verdict, the cause is always systemic: truncated diff, missing script path, stale task spec, corrupted prompt, file too large to read, or context exhaustion. Documentation-as-enforcement fails under context pressure — the retry tiers exist because the system must compensate for these structural limitations, not because agents are unreliable. Before retrying, query `yoke events tail --limit 20` to diagnose the failure mode.

## Blocking QA Waiver Rule

**NEVER auto-waive a blocking QA requirement.** If a blocking requirement (`blocking_mode='blocking'`) cannot be satisfied — e.g., no ephemeral URL available, browser daemon unreachable, test infrastructure down — **HALT and ask the operator**. Do not waive it, do not skip it, do not rationalize that the change is "trivial" or "visual-only." The requirement was made blocking for a reason.

The retained internal QA waiver path is **operator-debug only**, not normal product flow: it rejects waiving blocking requirements without `--force`. Only the human operator can authorize `--force` for blocking waivers. Non-blocking requirements can still be waived by the agent without `--force`.


**Multi-turn / multi-task progress notes.** Conduct frequently spans many turns and dispatches multiple subagents against the same epic. For session-continuity context that successor agents need to resume after compaction or a session swap, write to the **Progress Log** section on the epic item — see `AGENTS.md > Progress Log — long-running execution context on items`. Per-task progress notes still go to `epic_progress_notes` (already wired into the engineer-tester loop); the Progress Log on the epic item itself captures cross-task state (which tasks are stuck, which decisions were made at the epic level, where to resume).
