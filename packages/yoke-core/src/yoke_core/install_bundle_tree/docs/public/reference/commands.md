# Slash Commands Reference

Each command is a nested skill at `.agents/skills/yoke/{name}/SKILL.md`. Harnesses expose those commands through their native skill or slash-command surfaces; the shared `SKILL.md` frontmatter describes each procedure; `yoke_contracts.skill_registry` owns ids, kinds, session modes, autonomy, and dispatch classifications. Non-native harness surfaces invoke the same commands through their harness adapter's route wrapper (see the Harness Bootstrap Contract, yoke source-repo doc `docs/harness-bootstrap.md`, for command classification and the Hook Parity Map, yoke source-repo doc `docs/hook-parity-map.md`, for hook availability by harness). Render the operator-readable Atlas of the Yoke agent-facing surfaces (function ids, wrapped `yoke` subcommands, tool-shaped CLI adapters, permanent boundaries, pending rows, live contradictions) locally with `python3 -m yoke_core.tools.atlas_render_docs render`; each command below resolves to one or more registered function calls.

The registry below lists operator skills; internal sub-skills are called by orchestration commands. Large skills are decomposed into phase sub-files; top-level SKILL.md files should stay compact orchestration surfaces that delegate detailed sub-protocols to phase files. The 350-line file limit is implemented by `yoke_core.domain.file_line_check`, exposed to agents as `yoke check file-line`, and enforced everywhere the files themselves are readable — the pre-commit hook, the Dash survey's per-path sizing, and `HC-file-line-limit` in doctor. Lifecycle status writes do not enforce it: a control plane reached over https holds no checkout, so the limit is checked where the checkout is. **File Budget** is an independent pinned workflow policy: when enabled it shapes implementation before coding; when off, the same 350-line enforcement remains. File Budget/path-claim parity applies only when both effective axes are enabled. A small temporary-exception list covers strategic docs and prompt source-of-truth surfaces.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Operator Commands

<!-- BEGIN GENERATED: skill-registry -->
Skill metadata is generated from `yoke_contracts.skill_registry`.
Change that source and run `yoke dev run -- python3 -m
yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT`.

| Skill | Kind | Session mode | Autonomy | Purpose |
|---|---|---|---|---|
| `/yoke blitz {PREFIX-N}` | stage | `blitz` | autonomous execution | execute document-led work |
| `/yoke charge [--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]` | orchestrator | `charge` | autonomous execution | select runnable frontier work |
| `/yoke conduct PREFIX-N [--max-attempts N] [--no-chain]` | stage | `conduct` | autonomous execution | execute generated task lanes |
| `/yoke curate (no arguments)` | utility | `curate` | follow skill decision gates | curate the Ouroboros learning log |
| `/yoke dash "instruction" \| {PREFIX-N}` | stage | `dash` | autonomous execution | execute instruction-led work |
| `/yoke doctor [project] [--fix] [--file path]` | utility | `doctor` | follow skill decision gates | run health checks |
| `/yoke feed [--no-new-items] [PREFIX-N ...] [--model MODEL]` | orchestrator | `feed` | follow skill decision gates | refresh frontier work |
| `/yoke help` | utility | `operator` | follow skill decision gates | show command reference |
| `/yoke idea [--dry-run] [--workflow issue\|epic\|blitz\|task] {title}` | utility | `idea` | follow skill decision gates | file a backlog item |
| `/yoke implement {PREFIX-N} [--no-worktree] [--force] [--qa-bypass]` | stage | `implement` | autonomous execution | implement and review an item |
| `/yoke models lookup MODEL_ID \| get \| validate \| diff \| publish \| revisions \| restore \| level-proposal` | utility | `operator` | follow skill decision gates | publish model catalog revisions and propose level changes |
| `/yoke onboard [--project P] [--run-id RUN]` | orchestrator | `operator` | follow skill decision gates | make a wired project execution-ready |
| `/yoke polish {PREFIX-N}` | stage | `polish` | autonomous execution | review and finish implementation |
| `/yoke refine {PREFIX-N}` | stage | `refine` | follow skill decision gates | critique and improve item artifacts |
| `/yoke resync [--fix]` | utility | `operator` | follow skill decision gates | detect and repair GitHub drift |
| `/yoke shepherd {PREFIX-N}` | stage | `shepherd` | autonomous execution | execute the pinned planning interval |
| `/yoke simulate {epic-ref} [--auto-fix] \| --system` | utility | `simulate` | follow skill decision gates | trace integration paths; no terminal `yoke simulate` adapter |
| `/yoke steer [STRATEGY-DOC-SLUG] [--project P ...]` | orchestrator | `steer` | autonomous execution | staff work from a strategy document; omitted slug defaults to `CURRENT-PLAN` |
| `/yoke strategize [--model MODEL]` | orchestrator | `strategize` | follow skill decision gates | review project strategy |
| `/yoke usher PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]` | stage | `usher` | autonomous execution | merge and deliver an item |
| `/yoke wrapup (no arguments)` | utility | `wrapup` | follow skill decision gates | wrap up the session |
<!-- END GENERATED: skill-registry -->

## Local Terminal Helpers
These are operator-facing `yoke` CLI helpers that run directly in a terminal without a harness session; they are not lifecycle slash commands.

| Command | Description |
|---|---|
| `yoke dash TITLE INSTRUCTION` / `yoke task TITLE INSTRUCTION` | File direct work after resolving execution instructions: Dash owns a git lane and optional gates; Task is laneless and merge-free. |
| `yoke board art variant create --ascii\|--mixed\|--image PATH` | Generate, preview, and optionally apply `.yoke/board-art` variants |
| `yoke project snapshot sync [CHECKOUT]` | Scan committed git tree state and sync authoritative path snapshots |
| `yoke git pre-commit` | Run the installed pre-commit gate entrypoint. |
| `yoke git post-commit` | Run the installed post-commit path snapshot sync entrypoint. |
| `yoke dev path-snapshot-prewarm [PROJECT_ID]` | Source-dev/admin path-snapshot prewarm through local DB authority. Product hooks use `yoke project snapshot sync --hook`. |

### idea

Create a new backlog item. Infers type, priority, project, deployment flow, dependencies, and Pack-reuse stance from context; assigns the next `PREFIX-N` ID through the idea-intake creation path; then writes the body additively and syncs it to the linked GitHub issue when body content exists.

**Phase files:** `idea/infer-and-create.md` (field inference, cross-project gate, dedup, creation, dependency persistence) and `idea/body-and-sync.md` (mandatory body write, AC normalization, verification, GitHub body sync).

### shepherd

Execute the planning segment selected by the item's immutable Shepherd binding and generated-task policy. Read the ordered stages and declared edges; stage names and the handoff come from the binding. Each edge has a persisted verdict key derived from its source and target, with hyphens normalized to underscores and joined by `_to_`.

The first edge runs the conditional PM/design gates, Architect, and Simulator. Later edges review persisted artifacts; the final edge runs handoff quality gates and Boss review. A one-edge segment performs both roles before handoff. Accepted verdicts advance only the declared edge, with retries bounded at three attempts. Missing edges or an unsupported policy refuse with the pinned version and recovery named.

Resume from verdict history, artifacts, and live status. A Designer SKIPPED verdict skips only design. No legacy subagent invocation mode is supported. After handoff, refresh `items.detail.get` to report the actual stage and next bound skill.

**Structured fields:** `shepherd_log` and `shepherd_caveats` hold verdict evidence; Progress Log holds resumable execution context. The item body renders from these fields.

**Phase files:** `entry.md`, `transitions.md`, `design-and-plan.md`, `planning-gates.md`, `boss-verdict.md`, `finalize.md`.

### conduct

Single-item execution mode for epics:

- **`/yoke conduct PREFIX-N`** -- Single-item execution loop: start at `planned`, resume at `implementing` / `reviewing-implementation`, auto-resolve the next epic task, run Engineer + Tester, then finish with integration simulation and hand off at `reviewed-implementation`. Flags: `--no-chain`, `--max-attempts N`, `--force`/`--ignore-gaps`.
- Hard-block dependency blockers should be inspected with `yoke items dependency list PREFIX-N`, which reads the authoritative `item_dependencies` graph in both directions.

On first epic dispatch, runs the simulation gap gate (blocks if CRITICAL plan simulation gaps exist). Per-task diffs exceeding 300 lines are externalized to temp files. Conduct does NOT run merge/deploy; successful runs hand the parent epic to `/yoke polish PREFIX-N`.

**Thin Conduct Principle:** Conduct is an orchestrator, not an implementor. Its direct actions are limited to reading metadata, running status scripts, launching subagents (Engineer, Tester, Simulator), and parsing verdicts. All implementation and verification work happens inside subagents.

**Blocking QA Waiver Rule:** Never auto-waives blocking QA requirements. If a blocking requirement cannot be satisfied, conduct halts and asks the operator.

### usher

Unified merge+deploy pipeline skill. Takes `implemented` items through merge, deployment pipeline, and done-transition. Runs inline in main session (no subagent spawned). Decomposed into 5 phase files: collect, plan, merge, deploy, finalize.

**Arguments:** `PREFIX-N [PREFIX-N ...]` (explicit items), `--dry-run`, `--merge-only`, `--deploy-only`, `--resume PREFIX-N` (sugar for single-item deploy-only). No args: all release-eligible items for the default project.

Use `yoke items dependency list PREFIX-N` to inspect the authoritative dependency graph for any item. `/yoke usher --dry-run` surfaces the hard-block edges that explain its merge ordering.

**Pipeline phases:**

1. **Collect & Validate** -- Parse arguments, collect items, status gate (hard block for non-`implemented` items in standard mode; allows `release` / `implemented` in deploy-only mode), compute merge order, pre-merge CI check.
2. **Plan & Confirm** -- Dry run display (if `--dry-run` -> stop after), operator confirmation.
3. **Merge Execution** (skip if `--deploy-only`) --
 - **Release-before-merge ordering:** Items are advanced to `release` status (step 7b) before the merge executes, ensuring status reflects pipeline entry.
 - **Pre-merge ephemeral verification:** If the deployment flow includes an `ephemeral-verify` stage, runs ephemeral environment verification before merge. Skipped if already satisfied during conduct/polish.
 - **Merge engine:** Standalone items merge through `yoke merge item`. On merge-queue projects a relay-launched session always arms the landing and returns `landing_pending=true` naming the pull request — a headless command cannot outlive a queue landing, so the control-plane landing notice wakes it and the same command then completes close-out. Every other caller follows the landing to a terminal reading with the canonical `yoke watch merge --print-streaming-pair merge-item -- PREFIX-N --wait` call, which prints the safe invocation and merges nothing until you run it. The shared selector reads the caller's manifest wake capability: a native idle-wake primitive gets the background subscription and may release the caller, while a harness with no or unverified idle wake gets one foreground command to hold open. A bare default call also returns `landing_pending=true`; rely on a later completion message only when the selector recorded that primitive, otherwise re-enter through the canonical wait. Each wait cycle calls `merge_queue.landing.observe`; the server rate-limits concurrent callers to one project-wide GitHub sweep per cadence, refreshes all pending landings for the project, and returns this lane's durable `state`, `queue_holding`, `queue_entry_state`, `merge_when_ready`, check evidence, and refresh/change times. The waiting machine runs no `gh`/GitHub/`git fetch` read loop, and a machine-relay outage cannot stop refreshes triggered by live waiters. `landing_record_stale` names the last record/project refresh and the server-side recovery instead of falling back locally. A re-entry over a landing the control plane already recorded skips queue admission entirely and runs only that close-out, so a landing whose waiter died is recoverable rather than refused by an admission gate reading a train that has already run. Each arming records a fresh timestamp and has its own ejection notice identity, including when the same commit is re-armed; retrying an already-armed PR preserves its timestamp. A stopped landing retains its recorded admission until that notice reaches the recipient; an already-acknowledged dedupe refuses as `notice_already_acknowledged` and keeps the row visible, naming re-entry through `yoke merge item` to record a fresh arming. A red required-check set (failed required checks, nothing in flight) ends `--wait` immediately as a terminal failure, not a record-wait timeout. Non-queue projects retain the local locked merge. Epic items pass the epic_ref argument to the merge engine directly. `--keep-remote` on `merge_worktree` suppresses remote branch deletion so ephemeral environments persist.
 - **Known failed train:** `failed-train-unchanged` refuses queue re-entry for unchanged lane/base inputs and reports the observed run URL, exact combined head, and compared revisions. Inspect that identified failure first and correct its cause; re-enter only after relevant inputs change. When the URL is unavailable, use `yoke github-actions find-run <repo> <workflow-file> <commit-sha> --event merge_group --status failure --project <project>` with the reported combined head. Read that command's `--help` for diagnostic options. Empty commits, bypasses, and unanchored latest-run searches do not resolve the failure.
 - **Hard CI gate:** Merge failure (exit 1/4) halts the batch, reverts the item to `implemented`, and reports failure with resume instructions.
 - **Post-merge CI advisory:** After all merges complete, checks main branch CI status as an advisory (not blocking).
4. **Deployment Routing** (skip if `--merge-only`) --
 - **Route A (internal flows):** Items whose selected flow has no deploy target, or whose deployment flow is empty or null, go through the `yoke_core.engines.done_transition` skip-deploy path.
 - **Route B (deployment runs):** Items grouped by `(project, deployment_flow)`. Creates run, adds items, validates composition, claims preview env, and executes `yoke_core.domain.deploy_pipeline`.
 - **Inline approval:** When pipeline exits with code 2 (awaiting approval), usher resolves the gate context, prompts the operator via `AskUserQuestion` ("Yes, approve and continue" / "No, pause for later"), emits `DeploymentApprovalGranted` event, advances stages, and re-invokes the pipeline. No separate `/yoke approve` invocation needed within the usher flow.
5. **Finalize** -- Completion report with results per item and per deployment run. Pipeline failure recovery options documented: retry the failed stage through `/yoke usher`, skip a stage (update `current_stage` then resume), or abort the run. A failed run is never closed out as out-of-band delivery: `--skip-deploy` belongs to Route A's genuinely deploy-free flows, and recording a selected-flow delivery through it is a false record the close-out refuses once that flow has a succeeded run covering the merge.

**Idempotency:** Re-run on `done` items: silently skipped. Re-run on `release` items: skip merge, proceed to deployment. Re-run after approval: `--deploy-only` picks up from the approved stage. Partial batches skip items already at `done` / `release`.

### doctor

Run the Ouroboros health scan: checks across backlog, GitHub sync, worktrees, documentation drift, dispatch chains, agent prompts, hook scripts, schema validation, semantic drift, and more. `--fix` auto-repairs trivial issues. Report saved to `yoke/ouroboros/health/health-{YYYYMMDD}.md` (local, gitignored).

Which checks run is derived, not fixed: every check declares its project scope, source-tree dependence, supported runtimes, and required capabilities, and the runner resolves the applicable set for the target project and runtime. The project defaults to whichever one is bound to the checkout you are standing in. Checks outside the applicable set appear under `## Not Applicable` with their reason rather than as passes — a hosted run cannot see a source tree, so its source-tree checks report `N/A`, and exercising them means running doctor where the checkout lives. A project's own checks live in its `.yoke/doctor/` folder (`check_*.py` files, `hc_*` functions) and join the same report.

### freeze / thaw

`freeze PREFIX-N` -- Keep status, set `frozen=true`. `thaw PREFIX-N` -- Set `frozen=false`.

### block / unblock
`block PREFIX-N "<reason>"` -- Keep status, set the orthogonal blocked flag and reason on the item (cross-reference: see your `items` packet stanza) for waits with no blocking item; refuses when a live hard-block dependency edge already carries the wait (`yoke items dependency add`). Advance/merge/done-transition gates refuse forward progression, and a write to `done` evaluates closure-gated edges. `unblock PREFIX-N` clears both. Unrelated to a path-claim's `blocked` state (cross-reference: see your `path_claims` packet stanza).

### resync

Detect and repair drift between local backlog and GitHub issues. Three-stage pipeline: linkage (full outer join), field comparison (title, body, labels, state, comments), and repair. `--fix` for auto-repair.

### curate

Curate the Ouroboros learning log. Process unreviewed agent observations from the `ouroboros_entries` table -- cluster related entries by semantic similarity, route each actionable cluster to the output whose structure fits it (a Dash for a repair one session can execute from an instruction, a work item for a root cause needing agreed acceptance criteria or a task graph), and archive handled entries.

**Phase file:** `curate/cluster-and-work-item.md` (entry loading, clustering, code validation, duplicate checks, Dash promotion or work-item filing, review/archive state).

Supports project filtering (`--project <project-id>`). Runs inline in the main session -- no subagent needed.

### wrapup

Structured session wrap-up: Ouroboros reflections (captures observations to `ouroboros_entries`), unfinished business inventory, and session summary. Records continuity in item Progress Log and Ouroboros field-notes.

### refine

Standalone artifact-refinement mode. Reads an item's structured fields (`spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_caveats`, body fallback), critiques them for completeness, self-consistency, blast radius, cleanup coverage, failure/recovery coverage, and testability, and writes improvements back through the Yoke function-call surface (`items.structured_field.replace`, `items.structured_field.append_addendum`, `items.structured_field.section_upsert`, `items.structured_field.section_append`). Operator/debug callers use the matching `yoke items structured-field replace`, `yoke items structured-field append-addendum`, `yoke items structured-field section-upsert`, and `yoke items structured-field section-append` adapters, which construct a `FunctionCallRequest` internally and dispatch through the same registry. See [.yoke/docs/reference/db-reference/functions.md](db-reference/functions.md) for the envelope; render the operator-readable Atlas of registered surfaces locally with `python3 -m yoke_core.tools.atlas_render_docs render`. No worktree is required and no code is edited.

**Refine advances status on successful completion.** Issue entries transition `idea -> refining-idea -> refined-idea`; epic entries at `plan-drafted` / `refining-plan` transition through to `planned`. Failures leave the item at its current status. See [lifecycle.md](lifecycle.md) for the full command-boundary map.

Typical uses: tighten a sparse spec, normalize ACs into `AC-N` checkboxes, surface missing cleanup / recovery paths, or improve a planned epic's technical or worktree plan without re-running shepherd.

### polish

Standalone implementation-finishing mode. Resolves the item's implementation worktree lane set through the Yoke worktree resolver, reviews the current diff against the item's spec and technical plan, checks full AC coverage plus blast radius, cleanup, residue grep, test co-modification, and file-size risks, then makes targeted code or test fixes, runs verification from the changed worktree roots, and commits the result when changes were needed. Issue items usually resolve to one item worktree; epic items may resolve to multiple task worktrees recorded by conduct.

**Polish advances status on successful completion.** Read the item's exact pinned definition through `yoke workflows item get` and `yoke workflows version get`. The half-open `skill_bindings` interval containing the live stage must belong to `polish`; its `from_stage_id` and `through_stage_id` define entry and handoff. Activate and complete through declared forward edges with `yoke lifecycle transition`, running each target's attached QA against the committed lane. Failures leave the item at its current working stage. At `through_stage_id`, release the claim and render `next_skill_id` from a fresh item read; the next bound skill begins through a fresh command entrypoint. See [lifecycle.md](lifecycle.md).

Typical uses: vet a just-landed implementation, close small AC gaps or test failures, delete dead weight, perform ALTMAN-style finishing review without re-entering conduct.

### help

Show the Yoke command reference and quick-start guide. Also triggered by `/yoke` with no arguments.

### charge

Direct-mode entrypoint for the `charge` action. Computes the runnable frontier through the shared charge-frontier service (backed by `/v1/charge/frontier`), presents a ranked table of items with adapter classifications, confirms the top pick with the operator, and dispatches to the correct downstream skill (`refine`, `shepherd`, `conduct`, `implement`, `dash`, `blitz`, `polish`, or `usher`). See [charge-frontier.md](charge-frontier.md) for algorithm details, status-to-adapter mapping, and ranking criteria.

**Arguments:** `--dry-run` (show frontier, no dispatch), `--item PREFIX-N` (target specific item), `--project P` (explicit project scope; no guessed project), `--wip-cap N` (default: 5).

**Events:** `FrontierComputed` (emitted by core frontier path in `frontier.py`, not by charge directly), `ChargeDecisionMade` (on every terminal charge exit: dispatch, no runnable items, dry-run, unavailable explicit target, operator cancel, unexpected wait adapter).

### feed

Direct-mode entrypoint for SML-to-idea materialization, stale-work-item refresh, and frontier dependency graph maintenance. Feed reads the Strategic Markdown Layer (the MISSION, LANDSCAPE, VISION, and MASTER-PLAN docs rendered under .yoke/strategy/), the target frontier items, existing dependency edges, and recent codebase changes. It then converges on one or more of four valid outcomes:

1. **Leave work in the SML** -- the strategy layer contains potential work, but pulling it forward now is unsafe or premature.
2. **Refresh graph only** -- the frontier is sufficient but dependency facts are stale; reconcile generated edges without creating new items.
3. **Sharpen/split current frontier** -- existing items are underdefined or fused; refine them before adding unrelated new work.
4. **Materialize new work items** -- stable SML work can be pulled forward safely; create minimal useful new items and refresh the graph.

Feed is the canonical semantic owner of generated frontier-fact maintenance. It writes `source='feed'` dependency rows in `item_dependencies` with human-readable rationale and structured `evidence_json`, and it updates stale structured work-item fields when recent landed work changed the frontier's ground truth. It does not own ranking, WIP caps, or claim handling (those belong to the scheduler and charge).

**Arguments:** `--no-new-items` (run analysis and graph refresh without creating new items), optional `PREFIX-N ...` scope IDs, `--model MODEL`.

**Events:** `FeedStarted` (at run start), `FeedCompleted` (at run end with outcome summary).

### strategize

Direct-mode entrypoint for the `strategize` action. Guided interactive loop for Strategic Markdown Layer (SML) coherence. Refreshes SML files (the MISSION, LANDSCAPE, VISION, and MASTER-PLAN docs rendered under .yoke/strategy/) against recent reality, performs source-backed research, proposes changes, obtains operator approval at each checkpoint, and records a full audit trail. Strategize is the "compass" mode -- it ensures Yoke always has a clear, current strategy to charge against.

**Arguments:** `--model MODEL`.

**Checkpoint model:** The pipeline includes these operator checkpoints (numbered 0-5) where the operator can confirm, request corrections, or abort:
- Checkpoint 0: State refresh confirmation (delta summary review)
- Checkpoint 1: Problem framing (prioritized problem list)
- Checkpoint 2: Normative filter (research findings review)
- Checkpoint 3: SML change approval (proposed edits to SML files)
- Checkpoint 4: Frontier implication check (impact on backlog coherence)
- Checkpoint 5: Tradeoff resolution (only when conflicts detected)

**Lifecycle events:** `StrategizeStarted`, `SMLRefreshCompleted`, `SMLChangeProposed`, `SMLChangeApproved`. The latest `strategy_checkpoints.created_at` for the project bounds the delta window; checkpoints record completed strategize sessions and drift reviews.

**Phase files:** `strategize/refresh.md`, `strategize/research.md`, `strategize/propose.md`, `strategize/approve.md`, `strategize/finalize.md`.

## Internal Sub-skills

These are called by operator commands or other sub-skills. They have their own SKILL.md files and can be invoked directly, but are not part of the primary operator interface.

<!-- BEGIN GENERATED: skill-registry-internal -->
Internal skills are generated from `yoke_contracts.skill_registry`.

| Skill body | Purpose |
|---|---|
| `.agents/skills/yoke/amend/SKILL.md` | amend a synced task graph |
| `.agents/skills/yoke/approve/SKILL.md` | record a deployment approval |
| `.agents/skills/yoke/implement/implementing/SKILL.md` | kick off implementation |
<!-- END GENERATED: skill-registry-internal -->

The operator skill `simulate` is decomposed into `simulate/epic-flow.md`, `simulate/dispatch-prompts.md`, `simulate/autofix-loop.md`, and `simulate/system.md`. `usher/merge-generated-tasks.md` is an Usher phase file, rather than a separate skill body.

### implement

Stage skill for the segment a workflow binds to `implement` (issue: `refined-idea` up to `reviewed-implementation`). No target argument: the live stage decides whether it enters or re-enters. Flags (entry only): `--no-worktree` (evidence-only), `--force` (override gates), `--qa-bypass`.

1. **Entry** (`entry.md`) -- At the binding's entry stage, runs `yoke advance implementation-entry --item PREFIX-N`: preflight gates, then worktree preflight (claim, path-claim activation, worktree creation or reuse), the capability-gated environment phase, and the status write, in one process. Worktree creation is a filesystem + DB operation, not a session boundary; the session's authority over the lane is its work-claim, validated per tool call by `lint_session_cwd`. The orchestrator references are `worktree.md`, `activation.md`, `environment.md`.
2. **Re-entry** (`reentry.md`) -- Past the entry stage, recovers the registered lane and resumes implementation or the review loop without regressing status.
3. **Implementing sub-skill** (`implementing/`) -- QA seeding of the AC-verification requirement (`qa-seeding.md`), explicit Browser case authoring (`browser-seeding.md`), project context preflight from `context_routing` (`project-context.md`), test commands and QA recording (`test-and-record.md`), and implementation guidance (`implementation.md`). Items entering implementation outside conduct still seed QA requirements before work starts.
4. **Review loop** (`review.md`) -- Commits review fixes in the lane, refreshes affected QA cases, and writes each declared review stage with `yoke lifecycle transition`, reviews and fixes in place, and stops at the binding's handoff, rendering the next bound skill from `next_skill_id`. Capture-only runs (`execution_status='captured', verdict=NULL`) do not satisfy any `verdict='pass'` gate.

### approve

Human approval gate for the Usher deployment pipeline. Uses the run-based deployment model. Preconditions are validated by the approval-check domain path. The flow records the approval event, advances both the run's `current_stage` and each member item's `deploy_stage`, and handles edge cases: `complete` stage (already done), `-failed` stage (not approvable -- fix first).

**Arguments:** `PREFIX-N` (required), `--run <run-id>` (optional, auto-resolved if omitted), `--note "..."` (optional, recorded in event envelope).

### amend

Add, split, reassign, or remove tasks after sync. Routes mutations through the `workflow_item.epic_task.*` function family (`workflow_item.epic_task.add`, `workflow_item.epic_task.split`, `workflow_item.epic_task.reassign`, `workflow_item.epic_task.remove`, `workflow_item.epic_task.metadata_update`, `workflow_item.epic_task.body_replace`) and `workflow_item.epic_progress_note.append`. See [.yoke/docs/reference/db-reference/functions.md](db-reference/functions.md). Re-verifies worktree overlap. Creates new worktrees as needed.

### simulate

Auto-detects phase: plan (all tasks still pre-implementation, typically `planned`) or integration (all tasks `done`). Traces cross-task paths. `--force-integration` overrides phase detection. `--system` runs Ouroboros system-wide consistency audit across all agents, SKILLs, scripts, rules, hooks, and docs.

**Plan simulation:** Provides full task content inline. Simulator checks interface contracts, worktree visibility assumptions, dependency ordering, and merge sequence predictions. Includes failure path analysis.

**Integration simulation:** Compressed two-phase mode is the default. Uses extracted contracts, file overlap matrix, dependency edges, diff stats, and review summaries instead of full content. Simulator must produce a bounded preliminary verdict (Phase A, no tool calls) before selective verification (Phase B, max 5 file reads). Standard (full-context) path only used when `sim_force_standard_integration=true` in config.

**Auto-fix:** `simulate/autofix-loop.md` owns the shared Architect loop, capped at three passes. Direct use asks before fixes and re-simulation; `--auto-fix` accepts both automatically. Conduct delegates internally and routes remaining code gaps to its single amend cycle.

**System-wide simulation** (`--system`): Ouroboros audit of all Yoke components for consistency drift. Checks stale references, cross-agent assumption mismatches, hook references, and rule-implementation contradictions. Report saved to `yoke/ouroboros/health/` (local, gitignored). No auto-fix -- file work items via `/yoke idea`.

## Internal Support Artifacts

These are shared files used by multiple commands but are not slash commands themselves.

### `shared/tester-dispatch-template.md`

The sole Tester prompt template for item, generated-task, retry, and simulation-fix dispatches. Conduct and other implementation flows supply identity/spec, QA roster, project commands, registered lane, changed files, size-gated diffs, and ephemeral URL. Normal and minimal variants preserve the durable generated-task review receipt.

## Conduct Flags

| Flag | Default | Description |
|---|---|---|
| `PREFIX-N` | -- | Single-item mode: one Engineer/Tester loop |
| `--no-chain` | Off | Stop after current task (don't auto-chain to next) |
| `--max-attempts N` | 5 | Max Engineer/Tester cycles per item before halting |
| `--force` | Off | Override the simulation gap gate |
| `--ignore-gaps` | Off | Synonym for `--force` |

## Simulate Auto-Fix Flow

After `/yoke simulate {name}` completes its analysis, if any `[CRITICAL]` or `[WARNING]` gaps are found, the command offers to auto-fix them. The Architect subagent revises task specs based on the gap report. Fix loop runs a maximum of 3 iterations. Code-level gaps are skipped -- only plan-level fixes (task specs, acceptance criteria, file lists) are applied. Code fixes require `/yoke amend`.

## Simulation Gap Gate

A pre-dispatch quality gate that blocks epic dispatch when unresolved CRITICAL plan simulation gaps exist. The gate fires on the **first task dispatch** for an epic. The `--force` or `--ignore-gaps` flags on `/yoke conduct` override the gate. Implemented in `conduct/SKILL.md` (step 5f-epic.2a).

## Project Context Loading

Project context is loaded by multiple commands, not just conduct.

1. **Issue implementation entry** uses `implement/implementing/project-context.md` before the text-sensitive audit and file discovery. Reads project-wide always-included docs + topic list from `context_routing`, matches topics against title/spec/AC text, and emits a `Project Context Summary` with concrete implementation/test/doc surfaces.
2. **Conduct dispatch** appends a project-specific context bundle to Engineer/Tester prompts for every project-owned item via `dispatch-context.md` step `5f-project`.
3. Missing files warn and continue; broad exploration is fallback only when project docs already map the area.

**Tester-specific injection:** Conduct still includes `Project Test Commands` and `Ephemeral URL` in the Tester dispatch context.

## Key Patterns

- **Conduct auto-chains by default.** Chain state persists to DB. Survives crashes.
- **Project install is idempotent, and it publishes.** `yoke project install` repairs the external-project copy layer safely; `yoke dev setup` owns Yoke source-link/admin setup. A run fast-forwards the branch onto its remote before generating, commits the paths it owns, and pushes that commit; a remote that advanced mid-run is reconciled by regenerating on the new revision, never by a merge that would retain the older side's obsolete generated content. A protected branch gets the same commit on a `yoke-install/<sha>` branch plus a `github.pr.create` pull request; a push that cannot land reports `publication_pending` with the commit and recovery and exits `3`. Skipped-by-design outcomes: `--no-commit`, `--no-publish`, a remote-less checkout, and source-dev local-source apply. A branch holding the operator's own unpushed commits is reported, never published on their behalf.
- **Multi-project support.** Items carry an integer `project_id` referencing the `projects` table. Local checkout context comes from the machine config's env-scoped checkout→project list: each entry names the connection env whose universe its `project_id` belongs to (ids are numbered per universe), and a checkout that lives in several universes appears once per env, so it resolves only under a matching env. Shared project behavior lives in DB-backed project capabilities such as `project-policy` and `session-routing`; DB `project-policy.settings.board` owns renderer tuning and board scope for generated board output.
- **Unified operation access.** Agent-facing operations use registered function ids and their `yoke ...` adapters; raw diagnostic SELECTs use `yoke db read "SELECT ..."` when no first-class surface exists. `db_router query` is source-dev/operator-debug break-glass only.
- **Item delivery progress.** The in-product delivery summary is powered by the `item_progress_view` SQL view. There is no first-class item-progress adapter yet; use `yoke items get PREFIX-N`, `yoke qa gate-summary --item PREFIX-N --target reviewed-implementation`, and `/yoke usher --dry-run` for the currently wrapped item, QA, and merge/deploy views.
- **QA platform.** QA requirements, runs, and artifacts are exposed through `yoke qa ...` adapters such as `yoke qa requirement list`, `yoke qa run list`, and `yoke qa artifact add`. Items must have explicit `qa_requirements` before entering `reviewing-implementation`. Transition gating is enforced by the QA gates domain layer. See `.yoke/docs/reference/qa-platform.md`.
- **Self-serve body pattern.** Pipeline commands pass only metadata to subagents; subagents read the authoritative body from the DB themselves.
- **Post-merge pipeline (Usher).** After merge and QA, items reach `implemented`. The Usher creates deployment runs and owns the `implemented -> release -> done` transition. Items may halt at `needs-capability` or `awaiting-approval`.
