---
name: conduct
description: "Single-item execution orchestrator for epic items. Starts from `planned`, resumes at `implementing` / `reviewing-implementation`, runs Engineer + Tester plus integration simulation, and hands the parent epic off at `reviewed-implementation` for `/yoke polish`."
argument-hint: "YOK-N [--max-attempts N] [--no-chain]"
---

# /yoke conduct YOK-N

Run a single backlog item through the Engineer/Tester loop (epic items only).

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Issue-Type Rejection

**Conduct is epic-only.** If the target item has `type=issue`, reject immediately:

```
Error: /yoke conduct does not support issue items. YOK-{N} is type 'issue'.

Issue implementation routes through /yoke advance (main-session inline implementation).
Issue refinement routes through /yoke refine.
Issue polish routes through /yoke polish.

Run '/yoke advance YOK-{N} implementation' to begin issue implementation.
```

Check the item type early (in S2 or before the status gate) and halt before any worktree or status mutation.

## Autonomous Execution Mode

After every subagent returns, the conduct skill MUST immediately continue to the next step. Do not summarize, do not wait for user input. Each subagent return is a transition point, not a stopping point.

Worktree creation/activation is a pure filesystem + DB operation: `items.worktree` (branch slug) is set, path claims activate, and the same harness session continues directly into the Engineer/Tester loop — no manual relaunch, no parent-session stop, no claim handoff to a fresh session, no scope envelope. The parent session's authority over each activated worktree is the work-claim it (or its subagent) holds on that item; `lint_session_cwd` reads `work_claims` per tool call and validates target paths against the claimed worktree set + main control plane + free-path allowlist. The orchestrator does control-plane reads (`epic_progress_notes`, `yoke events query`, board rebuilds) freely from the same session — no bounce-throughs.

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

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Each Engineer and Tester dispatch starts with a cold context. The dispatch prompt must be self-contained — absolute paths, item metadata, diff content, test commands. Missing a single path or context variable costs an entire subagent session. The quality of the dispatch context directly determines the quality of the subagent's output.

**Codebase-reader naming travels through dispatch.** Assume future readers of the codebase will NOT have the ephemeral planning artifacts this conduct run is using. Engineer and Tester prompts must remind subagents that task specs are scaffolding, not naming source material: live names, comments, and current-state docs describe current function, purpose, mechanics, or domain role, never the ticket, plan, phase, task, AC, branch, worktree, or batch that produced them.

**No such thing as "agent error."** When the Engineer fails or the Tester returns no verdict, the cause is always systemic: truncated diff, missing script path, stale task spec, corrupted prompt, file too large to read, or context exhaustion. Documentation-as-enforcement fails under context pressure — the retry tiers exist because the system must compensate for these structural limitations, not because agents are unreliable. Before retrying, query `yoke events tail --limit 20` to diagnose the failure mode.

## Blocking QA Waiver Rule

**NEVER auto-waive a blocking QA requirement.** If a blocking requirement (`blocking_mode='blocking'`) cannot be satisfied — e.g., no ephemeral URL available, browser daemon unreachable, test infrastructure down — **HALT and ask the operator**. Do not waive it, do not skip it, do not rationalize that the change is "trivial" or "visual-only." The requirement was made blocking for a reason.

The retained internal QA waiver path is **operator-debug only**, not normal product flow: it rejects waiving blocking requirements without `--force`. Only the human operator can authorize `--force` for blocking waivers. Non-blocking requirements can still be waived by the agent without `--force`.

## Constants

<!-- NOTE: $SCRIPT_DIR is set once here but DOES NOT persist across Bash tool calls.
 Each Bash invocation is a fresh shell. In long conduct sessions (many engineer/tester
 dispatches, context pressure), Claude may copy literal `$SCRIPT_DIR` into late Bash calls
 instead of substituting the resolved value — producing `/python3 -m yoke_core.cli.db_router` (empty prefix).
 Mitigations: (1) entry-activation.md step S2 resolves SCRIPT_DIR to an absolute path via
 MAIN_ROOT. (2) Critical verdict-processing snippets use inline resolution
 (`SCRIPT_DIR="$(git rev-parse --show-toplevel)/.agents/skills/yoke/scripts"`)
 as a safety net. Do NOT copy bare $SCRIPT_DIR patterns into subagent dispatch prompts —
 subagents must inline full absolute paths.. -->
```
MAX_TESTER_REPROMPTS=2
MAX_SIMULATOR_REPROMPTS=2
MAX_ARCHITECT_FIX_ITERATIONS=3
```

**CRITICAL — Absolute path resolution:** `SCRIPT_DIR` starts as a relative path. After `MAIN_ROOT` is resolved (entry-activation step S2), **immediately** update it to an absolute path:
```bash
```
This prevents path breakage when the conduct skill `cd`s into worktrees. All subsequent `$SCRIPT_DIR` references will resolve correctly regardless of cwd.

**Tester output gate fallback chain:** When the Tester returns no parseable verdict, `MAX_TESTER_REPROMPTS` controls the escalation chain:
- **Initial attempt:** Full prompt with diff (inlined if <=300 lines, externalized to temp file if >300 lines). See `engineer-tester-loop.md` step 7. If verdict found, done.
- **Retry 1** (`_tester_output_failures == 1`): Minimal prompt variant (no inline diff, file list only) with default model. See `dispatch-context.md` step 5i-minimal.
- **Retry 2** (`_tester_output_failures == 2`): Minimal prompt variant + `model: "opus"`.
- **After retry 2** (`_tester_output_failures > MAX_TESTER_REPROMPTS`): Conduct direct verification fallback -- run tests in the worktree directly. See `dispatch-context.md` step 5i-conduct-verify. This is a documented exception to the Thin Conduct Principle.

The constant controls when to escalate model (retry 2) and when to fall back to conduct verification (after all retries exhausted). It does not control when to give up entirely -- the conduct skill always produces a verdict.

**Simulator output gate:** When the Simulator returns no parseable result (neither `SIMULATION: CLEAN` / `SIMULATION: GAPS FOUND` nor fallback `CLEAN` / `GAPS FOUND`), the gate first classifies the failure mode, then selects a recovery strategy. `MAX_SIMULATOR_REPROMPTS` controls the retry budget via a three-tier retry chain:
- **Initial attempt (Tier 1):** Compressed two-phase integration simulation by default, unless `sim_force_standard_integration=true` overrides it back to the standard full-context prompt. If result found, done.
- **Classification:** If no result found, classify output as `context_exhaustion` (< 500 chars, mid-thought fragment, tool-call reasoning without report structure) or `formatting_omission` (structured report content present, but the two-line verdict block — `SIMULATION:` line and/or `EPIC: YOK-{N}` attestation line — is missing). Ambiguous cases default to `formatting_omission` (conservative).
- **Retry 1 (Tier 2) — formatting_omission** (`_simulator_output_failures == 1`): Re-invoke with escalated instructions demanding the full two-line verdict block as the first two lines of the response.
- **Retry 1 (Tier 2) — context_exhaustion** (`_simulator_output_failures == 1`): Re-invoke with compressed context + two-phase protocol + aggressive constraints (verdict-first, max 3 gaps, forbidden-operations list). See `simulation-gate.md` S6h for the full retry prompt.
- **Retry 2 (Tier 3) — ultra-compressed no-tool fallback** (`_simulator_output_failures == 2`): Re-invoke with ultra-compressed context (overlap matrix + dependency edges + one-line task summaries only — no interface contracts, no review summaries, no diff stats) and a hard no-tool mandate. The Simulator must produce its verdict from prompt content alone. This trades depth for guaranteed completion. See `simulation-gate.md` S6h for the full ultra-compressed prompt.
- **After retry 2** (`_simulator_output_failures > MAX_SIMULATOR_REPROMPTS`): HALT (safe default). Unlike the Tester gate, there is no conduct direct-verification fallback -- the conduct skill cannot simulate integration paths itself.
- **Ouroboros logging:** All gate exhaustion entries include the failure mode classification and tier for pattern tracking.

The three-tier chain guarantees that at least one tier produces a parseable verdict for any epic size, trading depth for completion as tiers escalate. The Simulator already runs on opus, so no model escalation is needed.

## Arguments

Required:

- `YOK-N`: The backlog item to conduct. Run one item through the Engineer/Tester loop.

Optional flags:

- `--max-attempts N` (optional): override default retry limit. Default is **5**.
- `--no-chain` (optional, epic only): stop after the current epic task. Do not auto-dispatch the next task in the worktree chain.
- `--force` (optional): override simulation gap gate — proceed with dispatch even if CRITICAL gaps exist. Synonym for `--ignore-gaps`.
- `--ignore-gaps` (optional): synonym for `--force`. Either flag enables the override.
- `--no-auto-fix` (optional): skip the automatic fix loop on simulation gaps. When simulation finds gaps, HALT immediately (legacy behavior). Default: auto-fix is ON.

**Argument validation:**

If `YOK-N` is not provided, stop with:

> Missing required argument. Usage: `/yoke conduct YOK-N`

## Pre-Dispatch Gates

Before routing, enforce the dispatch gate and acceptance criteria gate.

1. **Dispatch gate (HARD BLOCK):** Read item status:
 ```bash
 _gate_status=$(yoke items get YOK-N status)
 ```
 - If `_gate_status` is `planned`, `implementing`, or `reviewing-implementation`: proceed.
 - Otherwise: hard-block with status-appropriate remediation:
 > GATE [hard-block]: Item not at a dispatchable status.
 > YOK-N is at status '{_gate_status}', not 'planned', 'implementing', or 'reviewing-implementation'.
 - `idea`, `refining-idea`: > Remediation: Run `/yoke refine YOK-N` to refine the spec.
 - `refined-idea`, `planning`: > Remediation: Run `/yoke shepherd YOK-N` to drive planning through `plan-drafted`.
 - `plan-drafted`, `refining-plan`: > Remediation: Run `/yoke refine YOK-N` to refine the plan to `planned`.
 - After `reviewing-implementation` (`reviewed-implementation`, `polishing-implementation`): > Remediation: Run `/yoke polish YOK-N` to finish implementation polish.
 - `implemented` or `release`: > Remediation: Run `/yoke usher YOK-N` to merge and deploy.
 - `done`: > Item is already done. No conduct needed.
 - Exceptional (`blocked`, `stopped`, `failed`, `cancelled`): > Item is in an exceptional state. Resolve the block or use an explicit operator-debug repair path before retrying.

2. **Acceptance criteria gate (HARD BLOCK):** Read item spec (structured field first, body fallback):
 ```bash
 _gate_body=$(yoke items get YOK-N spec 2>/dev/null)
 if [ -z "$_gate_body" ]; then
 _gate_body=$(yoke items get YOK-N body)
 fi
 ```
 - Search for AC patterns: lines matching canonical `- [ ] AC-` rows or unlabeled `- [ ] ` checkboxes under a `## Acceptance Criteria` section header.
 - If no ACs found: hard-block with:
 > GATE [hard-block]: Missing acceptance criteria.
 > YOK-N has no acceptance criteria. Conduct requires ACs to verify.
 > Remediation: Run '/yoke shepherd YOK-N' to add acceptance criteria.

3. **Activation dependency gate (HARD BLOCK):** Use the shared hard-block dependency checker with activation-only semantics. Conduct start gating evaluates only `activation` blockers — `integration` and `closure` edges are enforced downstream by merge/usher gates, not at dispatch time:
 ```bash
 _dep_output_file=$(mktemp "${TMPDIR:-/tmp}/conduct-hard-blocks.XXXXXX")
 if python3 -m yoke_core.domain.check_hard_blocks "YOK-N" --gate-point activation >"$_dep_output_file" 2>/dev/null; then
 _dep_exit=0
 else
 _dep_exit=$?
 fi
 _dep_output=$(cat "$_dep_output_file")
 rm -f "$_dep_output_file"
 ```
 - If `_dep_exit` is non-zero, hard-block with:
 > GATE [hard-block]: Unresolved activation dependencies.
 > YOK-N has unresolved activation dependencies that must be satisfied before conduct dispatch.
 - For each `BLOCKED|YOK-{M}|{status}|{title}` line in `_dep_output`, list:
 > - **YOK-{M}** ({title}): status `{status}`
 - Then print the authoritative inspection command:
 > Inspect the full dependency graph (both directions):
 > `yoke shepherd dependency-list YOK-N`
 - Do NOT proceed to dispatch.
 - If `_dep_exit` is 0, continue.

## Phased-Read Plan

After pre-dispatch gates pass, follow this phased-read sequence. **Do NOT read all files upfront.** Read each phase file only when you reach that phase in execution. This preserves context budget for the subagent dispatches that consume the majority of a conduct session.

| Phase | File | When to read | Approx size |
|---|---|---|---|
| 1. Entry & Activation | `entry-activation.md` | **Always — read first** | ~300 lines |
| 2. Engineer/Tester Loop | `engineer-tester-loop.md` | After activation completes (S6f done) | ~340 lines |
| 3. Simulation Gate | `simulation-gate.md` | After all tasks pass (all `reviewed-implementation`) | ~370 lines |
| 4. Cleanup & Report | `cleanup-report.md` | After simulation (or on any exit path) | ~100 lines |

**Supplemental files — read only when a phase step references them:**

| File | Read when | Safe-read guidance |
|---|---|---|
| `dispatch-context.md` (~1445 lines) | Steps in the loop reference specific sections (5f-rehydrate, 5m, 5n, 5i-minimal, etc.) | **Read only the referenced section.** Use `offset`/`limit` on the Read tool: section index is at the top of the file. Never read end-to-end. |
| `simulation-autofix.md` (~582 lines) | `simulation-gate.md` Branch 3 (GAPS FOUND with CRITICALs) | Read fully only when entering the autofix flow. |
| `error-handling.md` (~61 lines) | Reference only — halt conditions and non-halting failure notes | Small enough to read in full when needed. |

**Large-file read discipline for subagent dispatch prompts:** When a phase file builds an Engineer, Tester, or Simulator prompt that references known-large documents (task bodies, diffs, specs), that phase file includes explicit size-gate guidance. Follow it — do not blind-read oversized content into prompts.

### Phase execution

1. Read `.agents/skills/yoke/conduct/entry-activation.md` and follow it (S1–S6f).
2. When entry-activation hands off to the loop, read `.agents/skills/yoke/conduct/engineer-tester-loop.md` and follow it (S6g).
3. When all tasks are complete or the loop exits, read `.agents/skills/yoke/conduct/simulation-gate.md` and follow it (S6h).
4. On every exit path (SUCCESS, HALTED, `--no-chain`), read `.agents/skills/yoke/conduct/cleanup-report.md` and follow it (6z, 6z-cleanup, 7).

**`single-item.md` is retained as a thin index** that cross-references the phase files and preserves the shell reminder and argument-parsing preamble. It is no longer the sole execution surface — each phase file is self-contained.

**Multi-turn / multi-task progress notes.** Conduct frequently spans many turns and dispatches multiple subagents against the same epic. For session-continuity context that successor agents need to resume after compaction or a session swap, write to the **Progress Log** section on the epic item — see `AGENTS.md > Progress Log — long-running execution context on items`. Per-task progress notes still go to `epic_progress_notes` (already wired into the engineer-tester loop); the Progress Log on the epic item itself captures cross-task state (which tasks are stuck, which decisions were made at the epic level, where to resume).

### Successor owner map

For adjacent tickets that target specific conduct responsibilities:

| Responsibility | Owner file | Notes |
|---|---|---|
| Submission remediation | `engineer-tester-loop.md` (step 5, submission gate) | Current owner for submission-gate routing |
| Reflection capture | `dispatch-context.md` (step 5m) | Unchanged — still in dispatch-context |
| Sync / cleanup | `entry-activation.md` (S6b auto-sync) + `cleanup-report.md` (6z-cleanup) | Split: sync at entry, cleanup at exit |
| Simulation gate | `simulation-gate.md` (S6h) | Current owner for integration simulation |
| Task fan-out enumeration | `entry-activation-resolution.md` (S6c) | Produces `_task_ids`; per-candidate same-worktree and dependency filters applied here |
| Parallel Engineer/Tester dispatch | `dispatch-context-dispatch.md` (5g/5h) + `dispatch-context-prompts.md` (5i) | Live execution path for `_batch_size > 1`; routed from `engineer-tester-loop.md` Branch B |
