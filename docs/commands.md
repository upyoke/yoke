# Slash Commands Reference

Each command is a nested skill at `.agents/skills/yoke/{name}/SKILL.md`. Harnesses expose those commands through their native skill or slash-command surfaces; the shared `SKILL.md` frontmatter is the single authored metadata source. Non-native harness surfaces invoke the same commands through their harness adapter's route wrapper (see [Harness Bootstrap Contract](harness-bootstrap.md) for command classification and [Hook Parity Map](hook-parity-map.md) for hook availability by harness). The operator-readable Atlas of the Yoke agent-facing surfaces (function ids, wrapped `yoke` subcommands, permanent boundaries, pending rows, live contradictions) lives at [`docs/atlas.md`](atlas.md); each command below resolves to one or more registered function calls.

Yoke has **20 operator commands** (the primary interface) and **6 internal sub-skills** (called by other commands, not typically invoked directly). Large skills are decomposed into phase sub-files; top-level SKILL.md files should stay compact orchestration surfaces that delegate detailed sub-protocols to phase files. The 350-line file limit is implemented by `yoke_core.domain.file_line_check`, exposed to agents as `yoke check file-line`, and enforced at pre-commit, advance/polish status gates, and `HC-file-line-limit` in doctor; the upstream **File Budget** contract (seeded by `/yoke idea`, hardened by `/yoke refine`, propagated through architect plans and Engineer dispatch) shapes implementation work to fit the limit before coding begins so the late-stage gates rarely fire. A small temporary-exception list covers strategic docs and prompt source-of-truth surfaces.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Operator Commands

| Command | Description |
|---|---|
| `/yoke idea {title}` | Capture a new backlog item with dedup search and GitHub sync |
| `/yoke shepherd YOK-N` | Drive an epic from `refined-idea` through quality-gated planning to `planned` |
| `/yoke conduct YOK-N` | Engineer/Tester loop for a single epic |
| `/yoke usher [YOK-N]` | Merge and deploy `implemented` / `release` items through the deployment pipeline |
| `/yoke doctor [project]` | Health checks and diagnostics (`--fix` for auto-repair) |
| `/yoke freeze YOK-N` / `/yoke thaw YOK-N` | Freeze / thaw an item (keep status, set/clear frozen flag) |
| `/yoke block YOK-N "<reason>"` / `/yoke unblock YOK-N` | Block / unblock (preserves lifecycle status; sets the orthogonal blocked flag) |
| `/yoke resync` | Detect and repair drift between local backlog and GitHub issues |
| `/yoke curate` | Curate the Ouroboros learning log -- cluster, archive, promote patterns |
| `/yoke wrapup` | Structured session wrap-up with ouroboros reflections |
| `/yoke refine YOK-N` | Critique and improve item artifacts without touching code or worktrees |
| `/yoke advance YOK-N implementation` | Issue implementation entry: create or re-enter the worktree in the same harness session (no relaunch), then run the implementation/review loop under the work-claim acquired in preflight |
| `/yoke polish YOK-N` | Review and finish implementation in the item's existing worktree lane(s) |
| `/yoke help` | Show command reference (also: `/yoke` with no args) |
| `/yoke do` | Autonomous session orchestrator -- offers session to decision engine, routes to chosen mode |
| `/yoke charge` | Direct-mode entrypoint -- pick up next runnable item from frontier, begin implementation |
| `/yoke feed [--no-new-tickets] [YOK-N ...]` | Direct-mode entrypoint -- refresh stale frontier items, maintain dependency graph truth, and materialize new work from strategy |
| `/yoke strategize` | Direct-mode entrypoint -- guided SML review (research, propose, approve) |

## Local Terminal Helpers
These are operator-facing `yoke` CLI helpers that run directly in a terminal without a harness session; they are not lifecycle slash commands.

| Command | Description |
|---|---|
| `yoke board art variant create --ascii\|--mixed\|--image PATH` | Generate, preview, and optionally apply `.yoke/board-art` variants |
| `yoke project snapshot sync [CHECKOUT]` | Scan committed git tree state and sync authoritative path snapshots |
| `yoke git pre-commit` | Run the installed pre-commit gate entrypoint. |
| `yoke git post-commit` | Run the installed post-commit path snapshot sync entrypoint. |
| `yoke dev path-snapshot-prewarm [PROJECT_ID]` | Source-dev/admin path-snapshot prewarm through local DB authority. Product hooks use `yoke project snapshot sync --hook`. |

### idea

Create a new backlog item. Infers type, priority, project, deployment flow, dependencies, and Pack-reuse stance from context; assigns the next `YOK-N` ID through the idea-intake creation path; then writes the body additively and syncs it to the linked GitHub issue when body content exists.

**Phase files:** `idea/infer-and-create.md` (field inference, cross-project gate, dedup, creation, dependency persistence) and `idea/body-and-sync.md` (mandatory body write, AC normalization, verification, GitHub body sync).

### shepherd

Advance an epic from `refined-idea` to `planned` through quality-gated transitions. Epic-only (issues use `/yoke refine` instead). For each transition: Worker produces the artifact, Boss reviews, the verdict is persisted, and the pipeline advances or retries.

**Modes:** Standalone mode (interactive, pauses between transitions) and subagent mode (`--subagent --session <id>`, autonomous).

**Transition routing:**
- `refined_idea_to_planning` -- PM spec-writing gate (invoked when the spec lacks required PRD sections) + Architect decomposes into epic tasks or produces a lightweight technical plan. Simulator runs the plan-phase simulation with the auto-fix loop (max 2 cycles).
- `planning_to_plan_drafted` -- No worker; runs quality gates (missing AC hard-block, missing deployment flow hard-block, Pack-reuse stance advisory for non-yoke items, vague AC advisory, scope overlap advisory, epic task independence advisory), then Boss final review.

**Resume support:** Queries `shepherd_verdicts` table. Completed (READY/CAVEATS/SKIPPED) transitions are skipped. BLOCKED transitions halt. NOT_READY transitions resume at the next attempt (max 3). Re-anchoring blocks between transitions prevent context pollution from instruction-like spec bodies.

**Structured field isolation:** Shepherd writes to `shepherd_log` and `shepherd_caveats` fields -- the body is automatically re-rendered by `render-body.sh`. Body content isolation rules prevent spec content from leaking into orchestration context.

**Phase files:** `design-and-plan.md`, `planning-to-planned-gates.md`, `boss-verdict.md`, `finalize.md`.

### conduct

Single-item execution mode for epics:

- **`/yoke conduct YOK-N`** -- Single-item execution loop: start at `planned`, resume at `implementing` / `reviewing-implementation`, auto-resolve the next epic task, run Engineer + Tester, then finish with integration simulation and hand off at `reviewed-implementation`. Flags: `--no-chain`, `--max-attempts N`, `--force`/`--ignore-gaps`.
- Hard-block dependency blockers should be inspected with `yoke shepherd dependency-list YOK-N`, which reads the authoritative `item_dependencies` graph in both directions.

On first epic dispatch, runs the simulation gap gate (blocks if CRITICAL plan simulation gaps exist). Per-task diffs exceeding 300 lines are externalized to temp files. Conduct does NOT run merge/deploy; successful runs hand the parent epic to `/yoke polish YOK-N`.

**Thin Conduct Principle:** Conduct is an orchestrator, not an implementor. Its direct actions are limited to reading metadata, running status scripts, launching subagents (Engineer, Tester, Simulator), and parsing verdicts. All implementation and verification work happens inside subagents.

**Blocking QA Waiver Rule:** Never auto-waives blocking QA requirements. If a blocking requirement cannot be satisfied, conduct halts and asks the operator.

### usher

Unified merge+deploy pipeline skill. Takes `implemented` items through merge, deployment pipeline, and done-transition. Runs inline in main session (no subagent spawned). Decomposed into 5 phase files: collect, plan, merge, deploy, finalize.

**Arguments:** `YOK-N [YOK-N ...]` (explicit items), `--dry-run`, `--merge-only`, `--deploy-only`, `--resume YOK-N` (sugar for single-item deploy-only). No args: all release-eligible items for the default project.

Use `yoke shepherd dependency-list YOK-N` to inspect the authoritative dependency graph for any item. `/yoke usher --dry-run` surfaces the hard-block edges that explain its merge ordering.

**Pipeline phases:**

1. **Collect & Validate** -- Parse arguments, collect items, status gate (hard block for non-`implemented` items in standard mode; allows `release` / `implemented` in deploy-only mode), compute merge order, pre-merge CI check.
2. **Plan & Confirm** -- Dry run display (if `--dry-run` -> stop after), operator confirmation.
3. **Merge Execution** (skip if `--deploy-only`) --
 - **Release-before-merge ordering:** Items are advanced to `release` status (step 7b) before the merge executes, ensuring status reflects pipeline entry.
 - **Pre-merge ephemeral verification:** If the deployment flow includes an `ephemeral-verify` stage, runs ephemeral environment verification before merge. Skipped if already satisfied during conduct/polish.
 - **Merge engine:** Standalone items invoke the `yoke_core.engines.merge_worktree` engine on the issue-merge boundary, where the engine-owned `YOKE_DONE_TRANSITION=1` standalone-branch contract applies (set internally by `yoke_core.engines.done_transition` for the epic path, and set on the boundary call for the issue path — both are the same engine contract, not an ad-hoc bypass). Epic items pass the epic_ref argument. `--keep-remote` on `merge_worktree` suppresses remote branch deletion so ephemeral environments persist.
 - **Hard CI gate:** Merge failure (exit 1/4) halts the batch, reverts the item to `implemented`, and reports failure with resume instructions.
 - **Post-merge CI advisory:** After all merges complete, checks main branch CI status as an advisory (not blocking).
4. **Deployment Routing** (skip if `--merge-only`) --
 - **Route A (internal flows):** Items whose selected flow has no deploy target, or whose deployment flow is empty or null, go through the `yoke_core.engines.done_transition` skip-deploy path.
 - **Route B (deployment runs):** Items grouped by `(project, deployment_flow)`. Creates run, adds items, validates composition, claims preview env, and executes `yoke_core.domain.deploy_pipeline`.
 - **Inline approval:** When pipeline exits with code 2 (awaiting approval), usher resolves the gate context, prompts the operator via `AskUserQuestion` ("Yes, approve and continue" / "No, pause for later"), emits `DeploymentApprovalGranted` event, advances stages, and re-invokes the pipeline. No separate `/yoke approve` invocation needed within the usher flow.
5. **Finalize** -- Completion report with results per item and per deployment run. Pipeline failure recovery options documented: retry the failed stage through `/yoke usher`, skip a stage (update `current_stage` then resume), manual completion (`--skip-deploy`), or abort.

**Idempotency:** Re-run on `done` items: silently skipped. Re-run on `release` items: skip merge, proceed to deployment. Re-run after approval: `--deploy-only` picks up from the approved stage. Partial batches skip items already at `done` / `release`.

### doctor

Run the Ouroboros health scan: 40+ checks across backlog, GitHub sync, worktrees, documentation drift, dispatch chains, agent prompts, hook scripts, schema validation, semantic drift, and more. `--fix` auto-repairs trivial issues. Report saved to `yoke/ouroboros/health/health-{YYYYMMDD}.md` (local, gitignored).

### freeze / thaw

`freeze YOK-N` -- Keep status, set `frozen=true`. `thaw YOK-N` -- Set `frozen=false`.

### block / unblock
`block YOK-N "<reason>"` -- Keep status, set the orthogonal blocked flag and reason on the item (cross-reference: see your `items` packet stanza); advance/merge/done-transition gates refuse forward progression. `unblock YOK-N` clears both. Unrelated to a path-claim's `blocked` state (cross-reference: see your `path_claims` packet stanza).

### resync

Detect and repair drift between local backlog and GitHub issues. Three-stage pipeline: linkage (full outer join), field comparison (title, body, labels, state, comments), and repair. `--fix` for auto-repair.

### curate

Curate the Ouroboros learning log. Process unreviewed agent observations from the `ouroboros_entries` table -- cluster related entries by semantic similarity, propose tickets for actionable clusters, archive old entries, and promote recurring patterns to `yoke/ouroboros/patterns.md`.

**Phase files:** `curate/cluster-and-ticket.md` (entry loading, clustering, code validation, duplicate checks, ticket filing, review/archive state) and `curate/patterns-and-retro.md` (pattern promotion and retrospective summary).

Supports project filtering (`--project <project-id>`). Runs inline in the main session -- no subagent needed.

### wrapup

Structured session wrap-up: ouroboros reflections (captures observations to `ouroboros_entries` table), unfinished business inventory, and session summary. Stores report in `wrapup_reports` table.

### refine

Standalone artifact-refinement mode. Reads an item's structured fields (`spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_caveats`, body fallback), critiques them for completeness, self-consistency, blast radius, cleanup coverage, failure/recovery coverage, and testability, and writes improvements back through the Yoke function-call surface (`items.structured_field.replace`, `items.structured_field.append_addendum`, `items.structured_field.section_upsert`, `items.structured_field.section_append`). Operator/debug callers use the matching `yoke items structured-field replace`, `yoke items structured-field append-addendum`, `yoke items structured-field section-upsert`, and `yoke items structured-field section-append` adapters, which construct a `FunctionCallRequest` internally and dispatch through the same registry. See [docs/db-reference/functions.md](db-reference/functions.md) for the envelope; the operator-readable Atlas of registered surfaces lives at [docs/atlas.md](atlas.md). No worktree is required and no code is edited.

**Refine advances status on successful completion.** Issue entries transition `idea -> refining-idea -> refined-idea`; epic entries at `plan-drafted` / `refining-plan` transition through to `planned`. Failures leave the item at its current status. See [lifecycle.md](lifecycle.md) for the full command-boundary map.

Typical uses: tighten a sparse spec, normalize ACs into `AC-N` checkboxes, surface missing cleanup / recovery paths, or improve a planned epic's technical or worktree plan without re-running shepherd.

### polish

Standalone implementation-finishing mode. Resolves the item's implementation worktree lane set through the Yoke worktree resolver, reviews the current diff against the item's spec and technical plan, checks full AC coverage plus blast radius, cleanup, residue grep, test co-modification, and file-size risks, then makes targeted code or test fixes, runs verification from the changed worktree roots, and commits the result when changes were needed. Issue items usually resolve to one item worktree; epic items may resolve to multiple task worktrees recorded by conduct.

**Polish advances status on successful completion.** Entry at `reviewed-implementation` transitions to `polishing-implementation` then to `implemented` once verification + browser QA pass. Failures leave the item at `polishing-implementation`. `implemented` is a handoff boundary — merge/deploy starts through a fresh `/yoke usher` command entrypoint, not by carrying polish's claim forward. See [lifecycle.md](lifecycle.md).

Typical uses: vet a just-landed implementation, close small AC gaps or test failures, delete dead weight, perform ALTMAN-style finishing review without re-entering conduct.

### help

Show the Yoke command reference and quick-start guide. Also triggered by `/yoke` with no arguments.

### do

Autonomous session orchestrator. Offers the current session to Yoke's decision engine, which inspects the frontier (runnable items, blocked items, SML state) and returns a `NextAction` directive. The directive is routed to the appropriate mode handler (charge, feed, strategize, wait, escalate). After a chainable mode completes, the loop re-offers automatically up to `max_chain_steps` times.

Operator-facing callers should enter this flow via `/yoke do`. The underlying session-offer adapter is an internal skill implementation detail, not a separate operator command.

**Arguments:** none. The session model is read from the current `harness_sessions` row (cross-reference: see your `harness_sessions` packet stanza), with `runtime.harness.hook_helpers_model.detect_model()` as the fallback when the stored row is absent or still placeholder-valued. When the session belongs to a project, the session lane is resolved from that project's DB-backed `session-routing` capability. The resolver walks the exact executor key (`executor_default_lane_claude_vscode`) -> wildcard key with the longest non-wildcard prefix (`executor_default_lane_claude*`) -> global `executor_default_lane_unknown` -> hardcoded `primary` chain inside that one project policy. Machine config is only the no-project/operator fallback.

**Environment variables:** `YOKE_EXECUTOR` (harness executor identity — explicit override, stored verbatim). When unset, Yoke hook helpers compose `{family}-{surface}` from the runtime entrypoint: Claude sessions read `CLAUDE_CODE_ENTRYPOINT` (observed values `claude-desktop`, `claude-vscode`); Codex sessions use the full entrypoint resolver (env -> transcript -> cache) and yield values such as `codex-cli`, `codex-vscode`, `codex-desktop`. Sessions with no surface signal fall back to the coarse `claude-code` / `codex` family value. The surface-specific form is **input** to session-begin; `harness_sessions.executor` stores only the canonical `harness_id` enum (`claude-code` / `codex`) — `canonical_harness_id()` in `runtime.harness.hook_helpers_identity` canonicalizes at write time, and the original surface-specific value is preserved in `harness_sessions.executor_display_name` for operator-facing UI. Both columns are **write-once** — written at initial `register_session` INSERT and persisted across reactivation; the canonical id and the display alias never change mid-session. `YOKE_PROVIDER` (model provider; defaults to `openai` for Codex-family sessions, otherwise `anthropic`). `supported_paths` is derived server-side from the shared registry plus the family manifest (`codex-*` -> `runtime/harness/codex/manifest.json`; `claude-*` -> `runtime/harness/claude-code/manifest.json`); third-party adapters without a Yoke-owned manifest may still pass `--supported-paths` to the shared session-offer API.

**Events:** Canonical `HarnessSessionOffered` and `NextActionChosen` events are emitted by the shared session-offer path, not by the loop directly. `ChainStepCompleted` is emitted after each handler returns, recording step, action, chainable, and handler outcome for chain-decision telemetry. All harnesses produce identical event lineage.

**Chain checkpoint:** After each mode handler returns, the loop persists a chain checkpoint on the session row via `session-checkpoint` (cross-reference: see your `harness_sessions` packet stanza for the checkpoint column). Step C reads it back via `session-checkpoint-read` to make the chain decision from durable state rather than prompt-local variables. This prevents dropped chains after long handlers (e.g., 50+ minute shepherd runs).

### charge

Direct-mode entrypoint for the `charge` action. Computes the runnable frontier through the shared charge-frontier service (backed by `/v1/charge/frontier`), presents a ranked table of items with adapter classifications, confirms the top pick with the operator, and dispatches to the correct downstream skill (`refine`, `shepherd`, `conduct`, `advance`, `polish`, or `usher`). See [charge-frontier.md](charge-frontier.md) for algorithm details, status-to-adapter mapping, and ranking criteria.

**Arguments:** `--dry-run` (show frontier, no dispatch), `--item YOK-N` (target specific item), `--project P` (default: `yoke`), `--wip-cap N` (default: 5).

**Events:** `FrontierComputed` (emitted by core frontier path in `frontier.py`, not by charge directly), `ChargeDecisionMade` (on every terminal charge exit: dispatch, no runnable items, dry-run, unavailable explicit target, operator cancel, unexpected wait adapter).

### feed

Direct-mode entrypoint for SML-to-idea materialization, stale-ticket refresh, and frontier dependency graph maintenance. Feed reads the Strategic Markdown Layer (the MISSION, LANDSCAPE, VISION, and MASTER-PLAN docs rendered under .yoke/strategy/), the target frontier items, existing dependency edges, and recent codebase changes. It then converges on one or more of four valid outcomes:

1. **Leave work in the SML** -- the strategy layer contains potential work, but pulling it forward now is unsafe or premature.
2. **Refresh graph only** -- the frontier is sufficient but dependency facts are stale; reconcile generated edges without creating new items.
3. **Sharpen/split current frontier** -- existing items are underdefined or fused; refine them before adding unrelated new work.
4. **Materialize new tickets** -- stable SML work can be pulled forward safely; create minimal useful new items and refresh the graph.

Feed is the canonical semantic owner of generated frontier-fact maintenance. It writes `source='feed'` dependency rows in `item_dependencies` with human-readable rationale and structured `evidence_json`, and it updates stale structured ticket fields when recent landed work changed the frontier's ground truth. It does not own ranking, WIP caps, or claim handling (those belong to the scheduler and charge).

**Arguments:** `--no-new-tickets` (run analysis and graph refresh without creating new items), optional `YOK-N ...` scope IDs, `--lane LANE`, `--model MODEL`.

**Events:** `FeedStarted` (at run start), `FeedCompleted` (at run end with outcome summary).

### strategize

Direct-mode entrypoint for the `strategize` action. Guided interactive loop for Strategic Markdown Layer (SML) coherence. Refreshes SML files (the MISSION, LANDSCAPE, VISION, and MASTER-PLAN docs rendered under .yoke/strategy/) against recent reality, performs source-backed research, proposes changes, obtains operator approval at each checkpoint, and records a full audit trail. Strategize is the "compass" mode -- it ensures Yoke always has a clear, current strategy to charge against.

**Arguments:** `--lane LANE`, `--model MODEL`.

**Checkpoint model:** The pipeline includes 6 operator checkpoints (numbered 0-5) where the operator can confirm, request corrections, or abort:
- Checkpoint 0: State refresh confirmation (delta summary review)
- Checkpoint 1: Problem framing (prioritized problem list)
- Checkpoint 2: Normative filter (research findings review)
- Checkpoint 3: SML change approval (proposed edits to SML files)
- Checkpoint 4: Frontier implication check (impact on backlog coherence)
- Checkpoint 5: Tradeoff resolution (only when conflicts detected)

**Lifecycle events:** `StrategizeStarted`, `SMLRefreshCompleted`, `SMLChangeProposed`, `SMLChangeApproved`, `StrategizeCompleted`. The `StrategizeCompleted` event timestamp serves as the delta-bounding marker for subsequent strategize sessions.

**Phase files:** `strategize/refresh.md`, `strategize/research.md`, `strategize/propose.md`, `strategize/approve.md`, `strategize/finalize.md`.

## Internal Sub-skills

These are called by operator commands or other sub-skills. They have their own SKILL.md files and can be invoked directly, but are not part of the primary operator interface. `/yoke advance` is dual-classified: `implementation` is the operator-facing issue entrypoint; other targets remain internal lifecycle transitions.

| Command | Called by | Description |
|---|---|---|
| `/yoke advance YOK-N [status]` | conduct, usher, do/loop, routed dispatch | Internal advance targets other than `implementation` |
| `/yoke merge {epic-id}` | usher | Sequential PR + CI + merge per branch |
| `/yoke approve YOK-N` | usher | Approve a deployment stage awaiting human approval |
| `/yoke amend {epic-id}` | conduct | Add, split, reassign, or remove tasks after sync |
| `/yoke plan {epic-id}` | shepherd, conduct | Architect planning: task decomposition or lightweight plan |
| `/yoke simulate {epic-id}` | conduct | Trace cross-task paths for integration gaps (`--system` for Ouroboros audit) |

`simulate` is decomposed into `simulate/epic-flow.md`, `simulate/dispatch-prompts.md`, `simulate/autofix-loop.md`, and `simulate/system.md`.

### advance

Advance an item's status forward. No args: auto-advance to next status. With status: jump to that status. Validates lifecycle order. In current delivery-family routing, issue implementation work commonly enters or resumes through `/yoke advance YOK-N implementation`, which normalizes to the canonical stored status `implementing`. Decomposed into 5 phase files plus the `implementing/` sub-skill (5 files).

**Flags:** `--env <name>` (update `deployed_to`), `--no-worktree` (skip worktree creation), `--force` (override gates).

**Phase dispatch:**
1. **Preflight** -- Type-aware dependency gates, lifecycle validation, merge verification gate, and done redirect.
2. **Worktree** (target = `implementing` only) -- Creates or re-enters the isolated worktree. Worktree creation is a pure filesystem + DB operation (records the worktree branch slug on the item and activates path claims; cross-reference: see your `items` packet stanza). The same harness session continues into implementation — no scope envelope, no claim release, no parent-stop, no manual relaunch. The session's authority over the worktree is its work-claim, validated per tool call by `lint_session_cwd` against the session's active claims (cross-reference: see your `work_claims` packet stanza).
3. **Implementation kickoff** (target = `implementing`) -- Seeds QA requirements, records test context, and prepares issue implementation work after the item enters `implementing`.
4. **Review-complete handoff** (target = `reviewed-implementation`) -- Re-runs browser screenshot QA on the latest review commit, inspects the captured screenshots, calls `yoke qa run complete --requirement-id <id> --run-id <capture> --verdict pass` to record inspection-verified quality, and only then bridges through `yoke qa screenshot-evidence satisfy --item YOK-N` to record that implementation review passed. Capture-only runs (`execution_status='captured', verdict=NULL`) do not satisfy any `verdict='pass'` gate.
5. **Finalize** -- Status update, GitHub sync, commit. For `implementing` target: hands off to `advance/implementing/SKILL.md`. For `reviewed-implementation`: emits next-step guidance to run `/yoke polish YOK-N`. For `implemented`: the next step is `/yoke usher YOK-N`.

**`advance/implementing` sub-skill:** Post-advance implementation kickoff called after status is set to `implementing`. Handles:
- **QA seeding** (`implementing/qa-seeding.md`): Seeds `qa_requirements` rows from acceptance criteria. Uses `ac_derived` as requirement source with AC-derived dedup. Seeds browser-testable requirements via `implementing/browser-seeding.md`, which reads the structured `browser_qa_metadata` field written at idea time and delegates scenario construction to `yoke_core.domain.qa_requirements.build_browser_requirements_from_metadata`. Seeds project E2E requirements when the project has an `e2e` command defined (in the `command_definitions` Project Structure family) and the `ephemeral-env` capability is registered.
- **Browser seeding** (`implementing/browser-seeding.md`): Seeds `browser_smoke` and `browser_diff` QA requirements for browser-testable items.
- **Project context preflight** (`implementing/project-context.md`): Reads the project-wide always-included docs and topic list from the `context_routing` Project Structure family, infers relevant topics from title/spec/AC text, and surfaces concrete implementation/test/doc paths before the text-sensitive audit and file discovery.
- **Test commands & QA recording** (`implementing/test-and-record.md`): Records test results as QA runs.
- **Implementation guidance** (`implementing/implementation.md`): Kickoff for implementation work.

**Worktree re-entry:** When current = `implementing` and target = `implementing`, locates the existing worktree (or recreates if missing). The same session continues — the work-claim acquired on first entry is still active and authorizes writes under the worktree via `lint_session_cwd`. The implementation/review loop resumes without re-advancing status.

**Review-lane re-entry:** When current = `reviewing-implementation` and target = `implementation`, `/yoke advance` resumes the same issue implementation worktree/review loop instead of regressing the stored status.

**Non-conduct QA seeding:** Items entering implementation outside the conduct pipeline (standalone `/yoke advance`) still seed QA requirements before implementation begins. The `advance/implementing/qa-seeding.md` phase ensures every item has requirements before work starts.

### merge

Sequential branch merge: rebase, auto-resolve generated files (branch-aware for doc files), PR, CI wait, merge. Post-merge: invokes Usher for deployment handoff.

### approve

Human approval gate for the Usher deployment pipeline. Uses the run-based deployment model. Preconditions are validated by the approval-check domain path. The flow records the approval event, advances both the run's `current_stage` and each member item's `deploy_stage`, and handles edge cases: `complete` stage (already done), `-failed` stage (not approvable -- fix first).

**Arguments:** `YOK-N` (required), `--run <run-id>` (optional, auto-resolved if omitted), `--note "..."` (optional, recorded in event envelope).

### amend

Add, split, reassign, or remove tasks after sync. Routes mutations through the `workflow_item.epic_task.*` function family (`workflow_item.epic_task.add`, `workflow_item.epic_task.split`, `workflow_item.epic_task.reassign`, `workflow_item.epic_task.remove`, `workflow_item.epic_task.metadata_update`, `workflow_item.epic_task.body_replace`) and `workflow_item.epic_progress_note.append`. See [docs/db-reference/functions.md](db-reference/functions.md). Re-verifies worktree overlap. Creates new worktrees as needed.

### plan

Explore scans codebase. Architect output is type-aware: issue -> lightweight `## Technical Plan` in item body, epic -> task decomposition + worktree plan. Recommends simulation for epics.

### simulate

Auto-detects phase: plan (all tasks still pre-implementation, typically `planned`) or integration (all tasks `done`). Traces cross-task paths. `--force-integration` overrides phase detection. `--system` runs Ouroboros system-wide consistency audit across all agents, SKILLs, scripts, rules, hooks, and docs.

**Plan simulation:** Provides full task content inline. Simulator checks interface contracts, worktree visibility assumptions, dependency ordering, and merge sequence predictions. Includes failure path analysis.

**Integration simulation:** Compressed two-phase mode is the default. Uses extracted contracts, file overlap matrix, dependency edges, diff stats, and review summaries instead of full content. Simulator must produce a bounded preliminary verdict (Phase A, no tool calls) before selective verification (Phase B, max 5 file reads). Standard (full-context) path only used when `sim_force_standard_integration=true` in config.

**Auto-fix (steps 8-12):** After gaps are found, offers to invoke the Architect in fix mode to revise task specs. Loop caps at 3 iterations. Code-level gaps are skipped -- only plan-level fixes applied.

**System-wide simulation** (`--system`): Ouroboros audit of all Yoke components for consistency drift. Checks stale references, cross-agent assumption mismatches, hook references, and rule-implementation contradictions. Report saved to `yoke/ouroboros/health/` (local, gitignored). No auto-fix -- file tickets via `/yoke idea`.

## Internal Support Artifacts

These are shared files used by multiple commands but are not slash commands themselves.

### `shared/tester-dispatch-template.md`

Defines the minimum structured context that any Tester dispatch MUST include. Referenced by `conduct/dispatch-context.md` (issue and epic task prompt templates) and `advance/implementing/SKILL.md` (ad-hoc Tester dispatch outside conduct). The template specifies required context blocks: item identity and spec, project test commands, changed files, QA requirements, ephemeral URL, and project context. Without this template, the Tester agent improvises its validation approach.

## Conduct Flags

| Flag | Default | Description |
|---|---|---|
| `YOK-N` | -- | Single-item mode: one Engineer/Tester loop |
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

1. **Issue implementation entry** uses `advance/implementing/project-context.md` before the text-sensitive audit and file discovery. Reads project-wide always-included docs + topic list from `context_routing`, matches topics against title/spec/AC text, and emits a `Project Context Summary` with concrete implementation/test/doc surfaces.
2. **Conduct dispatch** appends a project-specific context bundle to Engineer/Tester prompts for non-yoke project items via `dispatch-context.md` step `5f-project`.
3. Missing files warn and continue; broad exploration is fallback only when project docs already map the area.

**Tester-specific injection:** Conduct still includes `Project Test Commands` and `Ephemeral URL` in the Tester dispatch context.

## Key Patterns

- **Conduct auto-chains by default.** Chain state persists to DB. Survives crashes.
- **Project install is idempotent.** `yoke project install` repairs the external-project copy layer safely; `yoke dev setup` owns Yoke source-link/admin setup.
- **Multi-project support.** Items carry an integer `project_id` referencing the `projects` table. Local checkout context comes from the machine config's env-scoped checkout→project list: each entry names the connection env whose universe its `project_id` belongs to (ids are numbered per universe), and a checkout that lives in several universes appears once per env, so it resolves only under a matching env. Shared project behavior lives in DB-backed project capabilities such as `project-policy` and `session-routing`; project-local `.yoke/board.json` owns renderer tuning for generated board output in that checkout.
- **Unified operation access.** Agent-facing operations use registered function ids and their `yoke ...` adapters; raw diagnostic SELECTs use `yoke db read "SELECT ..."` when no first-class surface exists. `db_router query` is source-dev/operator-debug break-glass only.
- **Item delivery progress.** The in-product delivery summary is powered by the `item_progress_view` SQL view. There is no first-class item-progress adapter yet; use `yoke items get YOK-N`, `yoke qa gate-summary --item YOK-N --target reviewed-implementation`, and `/yoke usher --dry-run` for the currently wrapped item, QA, and merge/deploy views.
- **QA platform.** QA requirements, runs, and artifacts are exposed through `yoke qa ...` adapters such as `yoke qa requirement list`, `yoke qa run list`, and `yoke qa artifact add`. Items must have explicit `qa_requirements` before entering `reviewing-implementation`. Transition gating is enforced by the QA gates domain layer. See `docs/qa-platform.md`.
- **Self-serve body pattern.** Pipeline commands pass only metadata to subagents; subagents read the authoritative body from the DB themselves.
- **Post-merge pipeline (Usher).** After merge and QA, items reach `implemented`. The Usher creates deployment runs and owns the `implemented -> release -> done` transition. Items may halt at `needs-capability` or `awaiting-approval`.

## Archived Commands

These commands have been removed or tombstoned. Their SKILL.md files contain redirect stubs pointing to the replacement command.

| Removed Command | Replacement |
|---|---|
| `/yoke weave` | `/yoke usher` (merge + deploy in one pipeline) |
| `/yoke dispatch` | `/yoke conduct YOK-N` |
| `/yoke deploy` | `/yoke usher YOK-N` |
| `/yoke status` | Read generated `.yoke/BOARD.md` directly |
| `/yoke next` | `/yoke charge --dry-run` for the ranked runnable frontier |
| `/yoke standup` | `yoke items list --project all --fields "id,title,status,blocked"` |
| `/yoke blocked` | `yoke items list --blocked 1 --project all` |
| `/yoke stats` | No public wrapper; deployment-run stats are pending a first-class read surface, with raw SQL reserved for operator-debug escape hatch use |
| `/yoke backlog` | `yoke items list` |
| `/yoke design` | Called internally by `/yoke shepherd` |
| `/yoke sync` | Called internally by `/yoke conduct` |
| `/yoke docs-init` | Project documentation is created or maintained through project-specific docs work, not a slash-command bootstrap wrapper |
| `/yoke docs-update` | Manual or via `/yoke doctor` |
| `/yoke recover` | Re-run `/yoke conduct` (re-entry recovery) |
| `/yoke stop` | Session termination is handled by hooks |
| `/yoke import` | `/yoke idea` (one at a time) |
| `/yoke release-notes` | Standalone script, not a slash command |
