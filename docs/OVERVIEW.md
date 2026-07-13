> Orientation doc: describes the intended operating model and may lead the current implementation.

# Yoke — Architecture Overview

> **Field-note loop.** Yoke improves itself by capturing field-note signals from every agent — recipe gaps and minor bug observations alike. When a recipe is missing, wrong, or unclear, or an agent spots a small bug not worth a ticket, they log it inline; `/yoke curate` clusters the signals and fixes the source. The directive block is the contract.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## What Yoke Is

Yoke is becoming the operating core of an agentic company. The first type of company it is optimized to run is a company that delivers software products, and the first capability it owns is the software delivery lifecycle itself. In the current repo, that shows up as an attachable software-delivery operating layer: you make the key decisions, specialized AI subagents do the work, Postgres-backed state survives anything, Git worktrees enable parallel execution without conflicts, and QA/deployment evidence stays tied to the work. Yoke dogfoods its own infrastructure using the same pipeline it provides.

This first wedge is larger than it sounds. In a software product company, the software roadmap is often the company roadmap wearing a different name. Releases, bugs, quality decisions, and delivery cadence shape the business's real operating rhythm. That is why software delivery is the right first proving ground for Yoke rather than an arbitrary starting point.

Another framing: Yoke is trying to become a wish engine for company operations. Software delivery is the first proving ground.

At the Strategic Markdown Layer (SML), Yoke should keep `MISSION` for the one-line purpose statement, `LANDSCAPE` for source-backed external research and candidate imports, `VISION` for the chosen high-level future state and canonical visual, and `MASTER-PLAN` for the detailed evolving strategy. These SML docs live in the per-project `strategy_docs` DB table; `.yoke/strategy/*.md` are gitignored local views rendered from those rows. `Strategize` should first update the landscape, then selectively fold it into the vision and master plan, then shape the frontier until `feed` is coherent. Below that boundary, operational truth belongs in the database.

That suggests a product shape: operators should eventually launch workflows, not just commands. A workflow is an end-to-end execution path with ordered stages, gates, evidence, and a defined end state.

In practice, the near-term control surface should settle around four paths:

- `/yoke do` as the general session-offer loop
- `/yoke strategize` for guided Strategic Markdown Layer research and synthesis
- `/yoke feed` for maintaining frontier dependency facts and materializing strategy into ideas
- `/yoke charge` for moving the active frontier forward (see [charge-frontier.md](charge-frontier.md) for algorithm details)

Direct item commands such as `idea`, `shepherd`, `conduct`, and `usher` still matter, but as narrower downstream delivery adapters inside that control surface rather than as separate architectural centers.

Today that system is harness-neutral at the control-plane boundary: Yoke owns the state, approvals, evidence, and workflow logic, while reusable skill knowledge becomes portable across multiple agent environments. The [Harness Bootstrap Contract](harness-bootstrap.md) defines the neutral entry point for any harness -- startup reads, command classification (operator commands vs internal sub-skills vs raw scripts), repo-local skill discovery, and session identity expectations. Harness-specific adapters load this contract through thin wrappers, hooks, or native skill loaders, but the contract itself is Yoke-owned and harness-independent. The [Harness Adapter Template](harness-adapter-template.md) defines the five required parts every adapter must implement: bootstrap loader, capability manifest, session-offer builder, route wrapper, and smoke-test matrix. The [Hook Parity Map](hook-parity-map.md) classifies every hook by its availability tier across harnesses.

Cross-harness parity is now the operating model rather than a future direction. The Codex adapter (`runtime/harness/codex/`) covers the full Tier 1 operator surface listed in [`harness-bootstrap.md`](harness-bootstrap.md) §2 — including `/yoke conduct`. The shared Yoke registry supplies the entrypoints (`/yoke idea`, `/yoke do`, `/yoke refine`, `/yoke advance`, `/yoke conduct`, `/yoke polish`, `/yoke usher`) and downstream paths (`shepherd`, `refine`, `advance`, `conduct`, `polish`, `usher`); `runtime/harness/codex/manifest.json` declares identity, affordances, and explicit limitations rather than copying those lists. Codex sessions can file ideas, enter the session-offer loop, refine artifacts, drive epic conduct through the shared dispatch descriptor module that emits one task envelope per agent for both harnesses, open the issue implementation worktree via `/yoke advance YOK-N implementation`, finish implementations in that worktree, and perform explicit merge/deploy handoff through the top-level usher flow. The seven canonical agent bodies live at `runtime/agents/{agent}.md`; the substrate renderer fans them into `runtime/harness/claude/agents/yoke-*.md` for Claude and `runtime/harness/codex/agents/yoke-*.toml` for Codex, surfaced at `.claude/agents/` and `.codex/agents/` respectively, so the same prompt body ships to both harnesses. Codex also reads the canonical `.agents/skills/yoke` tree as repo-local skills, using the same `SKILL.md` frontmatter Claude reads. Hook-enhanced mode requires Codex >= 0.118.0-alpha.2; Yoke keeps the canonical hook pack at `runtime/harness/codex/hooks.json`, surfaced to Codex via `.codex/hooks.json`, and the working source-controlled launcher in `python3 -m runtime.harness.codex.codex_open_app`. When unavailable, the adapter falls back to wrapper-only mode where all correctness comes from Yoke core. The remaining named substrate gap is hook-edge: Codex has no `PostToolUseFailure` event for non-Bash tools, so Write/Edit/Read failures lack the dedicated event Claude emits — see [`hook-parity-map.md`](hook-parity-map.md) for the full tier breakdown. Canonical session-offer lineage (`HarnessSessionOffered`, `NextActionChosen` events) comes from the shared core path in `runtime/api/domain/sessions.py`, not from harness-local hooks. Yoke core derives each harness's `supported_paths` server-side from the shared registry plus manifest-declared limitations; harnesses do not self-report capabilities via `YOKE_SUPPORTED_PATHS`. The universal-source + per-harness-renderer model is documented in [`harness-substrate.md`](harness-substrate.md).

Long term it should also become multi-actor. Some people may launch or steer workflows from an attached harness, some may work mainly in a web approval surface, and some may contribute design or planning artifacts. Yoke should treat those as multiple actors collaborating through one shared workflow/evidence system.

That also means Yoke should become a real clearinghouse. Work may come from many channels and not all of it should become an item immediately. Yoke should classify and route incoming work into the right lane, and everything important should become a typed, traceable record even when it is not a backlog item.

The useful metaphor is organizational, not purely technical: Yoke becomes the company's front desk, main phone line, and mail room. Things arrive. They are identified. They are turned into the right kind of record. They are routed to the right lane and the right participant. Then the deeper workflow begins.

## The Pipeline

```
Core session loop:
 /yoke do -> core chooses resume | charge | feed | strategize | wait | escalate

Explicit strategic and frontier modes:
 /yoke strategize -> refresh state -> research -> propose SML changes -> approve -> finalize (6 operator checkpoints)
 /yoke feed -> gather context -> decide -> reconcile dependency graph -> optionally materialize new ideas -> summarize
 /yoke charge -> advance the active frontier -> route into delivery adapters

Downstream delivery adapters:
 idea -> shepherd -> charge lane -> usher
 (batch coordination is available when genuinely helpful)
```

You drive every phase transition. No phase auto-advances.

## Execution Ladder

Yoke should prefer the cheapest sufficient executor for each step:

- `D` — deterministic service / worker logic
- `J` — bounded LLM judgment with structured outputs
- `A` — full agentic execution with tools and iterative repo work

That means a workflow is not "one big agent session." It is an execution path whose stages can mix deterministic control-plane steps, bounded judgment calls, and only the genuinely open-ended agentic work.

## Multi-Actor Shape

The future product is not just "the operator dashboard." It is a shared clearinghouse with different participant types:

- workflow operators in an attached harness
- approvers and viewers in the website
- designers and planners contributing artifacts and decisions
- agents and workers executing bounded workflow stages

That means the control plane should eventually support teams, roles, permissions, workflow participants, approvals, artifact ownership, and audit trails as first-class concepts.

## Execution Ledger And Overrides

Under the workflows themselves, Yoke should maintain an execution ledger: one canonical record of intent, participants, state transitions, evidence, decisions, overrides, and outcomes.

In practice, that ledger should come from richly linked facts and derived traces rather than from forcing one giant wrapper around all work. Items often provide the main wrapper already; other explicit wrappers should appear only where the domain truly needs them.

That matters because the system should preserve causal truth. Yoke should be able to answer:

- what happened
- why it happened
- who did it
- what evidence supports it
- what is allowed to happen next

When work happens outside the standard execution path, the answer should not be "the framework kind of inferred it later." It should be an explicit manual override record with the actor, reason, evidence, and state effects attached.

**Project adoption prerequisite:** New projects must be installed and adopted before the Usher can operate. The product path is `yoke onboard`, then `yoke project create` / `yoke project import` / `yoke onboard project` or `yoke project install`, followed by `/yoke onboard-project` to configure Project Structure, strategy docs, capabilities, delivery settings, QA, and checklist evidence. GitHub labels, Actions variables/secrets, branch protection, environment protection, and project capability secrets are previewed and configured through Yoke surfaces, not ad-hoc bootstrap scripts.

## The Seven Agents + Orchestration Skills

| Agent | Model | Role | Key Constraint |
|---|---|---|---|
| Product Manager | opus | Rough idea → structured spec (in item body) | Read-only, no user interaction (subagent) |
| Product Designer | opus | Spec → UX/UI spec | Read-only, optional phase |
| Architect | opus | Spec → epic + tasks + worktree plan | Read-only + Bash for exploration |
| Engineer | opus | Implements task: code, tests, docs | Full tools, `bypassPermissions`, 300 turns |
| Tester | opus | Validates against spec, runs project-aware tests, traces paths, E2E against ephemeral URLs | Cannot modify code (3-layer enforcement) |
| Simulator | opus | Epic-level cross-task gap detection | Read-only (3-layer enforcement), optional |
| Boss | opus | Multi-perspective quality gate for specs, PRDs, and plans | Read-only + Bash, 300 turns |

> **Note:** Shepherd and Conduct orchestration runs inline via their respective SKILL.md files. They are skills/roles, not agents.

## File Layout

```
# Repo root — project artifacts
AGENTS.md # Project conventions (always loaded; CLAUDE.md is a compat symlink)
yoke/ # All Yoke state directories
├── BOARD.md # Sprint board (auto-generated)
├── docs/ # Architecture docs (agents read for cold starts)
├── releases/ # Release notes
├── context-archive/ # Archived implementation context
├── runtime/agents/ # Canonical agent behavior bodies ({agent}.md) — source of truth
├── ouroboros/ # Self-improvement system
├── data/ # Runtime config, backups, and generated views
├── api/ # FastAPI control plane service (localhost:8765)
│ ├── main.py # All v1 endpoints (health, items, board, write)
│ ├── domain/ # Shared Python domain layer (lifecycle, mutations, etc.)
│ ├── board/ # Python board renderer (hot path for BOARD.md)
│ │ ├── renderer.py # Top-level assembly (art + widgets + sections + zen)
│ │ ├── art.py # Art config, master map, header rendering
│ │ ├── widgets.py # Dashboard widgets (velocity, WIP, weather, etc.)
│ │ ├── sections.py # Board section classification and row rendering
│ │ ├── zen.py # Project timelines widget
│ │ └── __main__.py # CLI: python3 -m yoke_core.board preview
│ ├── requirements.txt # Pinned Python dependencies
│ └── test_api.py # API test suite (pytest)

# .claude/ — Claude adapter compatibility files
.claude/
├── settings.json # Permission rules
├── agents/ # Generated adapter files (yoke-*.md) — rendered from runtime/agents/ by agents_render
├── skills/yoke/
│ ├── SKILL.md # Root skill: routing + description
│ ├── {command}/SKILL.md # Nested skills (one per slash command)
│ └── scripts/ # Shell scripts (POSIX sh, all executable)
│ └── executors/ # Usher pipeline stage executors
└── rules/ # Project coding standards
```

## Backlog Registry

Every trackable item (idea, epic, issue) gets a stable `YOK-N` ID that persists through its entire lifecycle. The connected Postgres authority (`items` table) is the source of truth for all backlog item data. Item body content is read via `items get YOK-N body` (a virtual rendered field assembled on demand from structured fields). The auto-generated board in `.yoke/BOARD.md` shows all registry items grouped by status.

- **`/yoke idea {title}`** — Create a new item and assign the next `YOK-N` ID.
- **`yoke items list`** — List items with optional filters.
- **`yoke items get YOK-N body`** — Render the authoritative item body from structured fields.
- **`yoke <subcommand>`** — Registered command surface for items, workflow items, projects, events, QA, claims, and other function-backed operations.
- **`yoke board rebuild`** — Canonical board rebuild/terminal render entrypoint for `.yoke/BOARD.md`; add `--print` to print after writing or `--print-only` to render without writing.
- **Board preview helpers** — Source-dev/admin helpers for board art/widgets; see the Atlas before teaching a command-shaped recipe.

## Key Design Decisions

1. **Persistent state is the source of truth.** Not conversation memory. Operational state lives in the connected Postgres authority: backlog items and their structured design specifications, epic tasks, dispatch chains, QA requirements/runs/artifacts, progress notes, simulations, deployment flows, deployment runs, structured events, severity config, and ouroboros entries. Item body content is a virtual rendered field (read via `yoke items get YOK-N body`). DB access goes through registered `yoke ...` commands or the function-call surface, not through per-item markdown files or constructed file paths. A fresh session can pick up where the last left off.

2. **Session-aware decomposition.** Tasks are sized to fit in a single harness session. XL (>100k tokens) is never allowed. The Architect splits further if needed.

3. **Interface contracts.** Each task declares what it provides (exports) and expects (imports) with exact types and signatures. This prevents cross-task failures.

4. **Worktree independence.** Tasks in different worktrees cannot modify the same files. Verified by shell script during sync. Cross-session merge coordination via DB-based locking (`merge_locks` table) prevents concurrent merge operations from colliding when multiple Conduct sessions run in parallel.

5. **Multi-project isolation.** Yoke enforces strict project isolation. Every item is scoped to a project through the integer `items.project_id` field. Project and deployment flow are both set at creation time via `/yoke idea` (which prompts for project selection and deployment flow). An item's project determines which deployment flows are available; cross-project flow assignment is rejected. GitHub sync targets the correct repo per project, and each project carries a sync switch — `projects.github_sync_mode='backlog_only'` keeps a project's backlog DB-only, with every issue-sync surface skipping it (see `docs/github-sync.md`). The Python sync layer resolves repo and credentials per project through `yoke_core.domain.project_github_auth.resolve_project_github_auth`. Yoke and Buzz follow the same GitHub contract: the verified GitHub App repo binding is the sole outbound repository authority and mints short-lived bearer tokens for REST callers. `aws-admin` secrets and `ssh.private_key` are machine-local under `~/.yoke/secrets/capability-secrets/<project>/<capability>/`. No fallback to ambient host credentials. No env-var fallback chain. Broken project auth fails closed with a concrete repair command from `repair_command_hint`. Doctor `HC-wrong-repo-issues` validates GitHub issues exist in the correct repo per project. Local board rendering uses the machine config's checkout-to-project list for project context; that list is env-scoped (each entry names the connection env whose per-universe `project_id` it carries, and a checkout that lives in several universes appears once per env, so it resolves only under a matching env), and the machine project entry owns board `render_path` and user-scoped `scope`, while `.yoke/board.json` owns renderer tuning for the checkout that launched the render. Sprints are per-project: each project can have one active sprint simultaneously, enforced by a partial unique index. Tracks inherit project from their parent sprint. `yoke_core.engines.done_transition` resolves the item's project repo when looking for branches to merge. Doctor health checks validate project FK integrity, NULL-project violations (`HC-null-project-items`), item-flow project mismatches (`HC-invalid-item-flows`), cross-project sprint integrity (`HC-cross-project-sprint`, `HC-sprint-project-alignment`), and wrong-repo GitHub issues (`HC-wrong-repo-issues`).

6. **Hooks are deterministic.** Status updates, progress syncing, and cleanup run through Python hook entrypoints wired to each harness's hook events — not by LLM judgment. See `docs/hooks.md`.

7. **Self-discovering hooks.** Hooks use the harness-provided project root and the `epic_dispatch_chains` DB table to find the active task. No custom env vars are required for correctness.

8. **Unified Event Platform.** The `events` table is the single temporal log for system activity: tool calls, session lifecycle, status transitions, sync operations, conduct milestones, verdicts, and more. On the harness side, the observe hook emits `HarnessToolCallStarted`, `HarnessToolCallCompleted`, `HarnessToolCallFailed`, `HarnessToolCallStructuredExit`, and `HarnessLifecycleMutationDetected`, and the Yoke-owned PreToolUse lint deniers (`lint_db_cmd`, `lint_event_registry`, `lint_main_commit`, `lint_tc_label`, `lint_write_path`) emit `HarnessToolCallDenied` via the shared `emit_denial_event` helper in `runtime.harness.hook_runner.telemetry`. The DB-command guard preserves `lint-sqlite-cmd` only as a legacy stable telemetry/check id. Anomalies are stored on the primary tool-call row via `anomaly_flags`, not as a separate runtime event. Events follow a cross-stack structured logging standard (documented in `docs/structured-logging-standard.md`) with a canonical JSON envelope, property groups, and source-type composition. The event contract (`docs/event-contract.md`) defines the canonical envelope structure, naming conventions, execution context fields, and reserved patterns for downstream epics (DR-1, QA-1). `event_kind` is the semantic class of the event (`analytics`, `system`, `audit`, `security`, `metric`, `lifecycle`, `workflow`); emitter/source identity belongs in `source_type`, `service`, and registry ownership metadata. `yoke events ...` is the read/anomaly query surface. `yoke_core.domain.events.emit_event` is the universal emitter with session ID fallback chain and write-side severity gating; `YOKE_EVENTS_CAPTURE` mode enables test harness integration. **Event Registry Governance:** The `event_registry` table provides a central catalog of known event types with ownership, lifecycle status, and severity defaults. The pre-tool-use guardrail enforces registration for emit call sites, and the registry population helper maintains the catalog plus corrective metadata for runtime-owned events. Doctor health checks (`HC-event-registry-coverage`, `HC-event-emission-rate`, `HC-event-callsite-registry-sync`) audit registry completeness and call site synchronization.

9. **Ouroboros — Self-Improvement.** The system that eats its own tail, continuously learning and improving. Yoke manages its own development — it should also learn from itself. Four pillars:
 - **Agent Reflection:** Every agent answers 4 reflection questions at session end. Observations are captured automatically by the PostToolUse Agent-tool hook (`runtime/api/domain/reflection_capture_hook.py`) from `---REFLECTION-START---` blocks and persisted to the `ouroboros_entries` table.
 - **System-Wide Simulation:** `/yoke simulate --system` audits all agents, commands, scripts, rules, and docs for internal consistency drift.
 - **Health Checks:** `/yoke doctor` runs deterministic checks across the entire installation — backlog, GitHub, worktrees, docs, dispatch chains, agents, hooks, schema validation, semantic drift, orphaned stashes, stale sessions, GitHub state sync, size/bloat monitoring, backlog quality, GitHub orphan detection, bidirectional sync, session startup hook, documentation health audit, DB schema drift detection, event registry coverage, event emission rate, event call site registry sync.
 - **Learning Curation:** `/yoke curate` clusters agent observations, files tickets, archives old entries, and promotes recurring patterns to rules or code changes.

 The feedback loop: agents observe friction and ideas → log → curate clusters and tickets → doctor catches drift → fixes improve the system → agents observe better. Ouroboros is a headline feature — it's what makes Yoke compound its own intelligence over time.

## State Management

- **Backlog items:** The `items` table in the connected Postgres authority is the source of truth for all backlog item data (see your `items` packet stanza for the structured-field column list). All CRUD operations write to the DB; the rendered body is a virtual field — read via `items get YOK-N body`, which renders on demand from the stored structured fields. Content flows through structured field writes, which trigger GitHub sync.
- **Item status flow:** Issue items normally progress `idea` → `refining-idea` → `refined-idea` → `implementing` → `reviewing-implementation` → `reviewed-implementation` → `polishing-implementation` → `implemented` → `release` → `done`. Epic items add `planning` / `plan-drafted` / `refining-plan` before `planned`.
- **Epic tasks:** `epic_tasks` table — one row per task, keyed by `(epic_id, task_num)`. Status, body, github_issue, worktree, dispatch_attempts tracked in DB.
- **Dispatch chains:** `epic_dispatch_chains` table — ordered task queue per worktree, with current_index and attempt tracking.
- **Task history:** `events` rows with `event_type='task_status_change'` — epic task status transition log with timestamps and envelope detail.
- **Reviews:** Stored in `qa_requirements` + `qa_runs` with `qa_kind='implementation_review'`; epic task helpers use `yoke workflow-item epic-task review-insert ... --body-file <path>` (stdin fallback supported) and `yoke workflow-item epic-task review-get`.
- **Progress notes:** `epic_progress_notes` table — per-task progress with GitHub sync tracking.
- **Simulations:** Stored in `qa_runs` table via `yoke workflow-item epic-task simulation-upsert` — plan and integration phase simulation reports.
- **Events:** `events` table — structured telemetry events (tool calls, session lifecycle, anomalies). Keyed by `event_id` (UUID, idempotent insert/upsert for deduplication). Filterable by `source_type`, `session_id`, `event_name`, `tool_name`, `project` through `yoke events query`; write-side severity gating uses the `severity_config` table.
- **Projects:** `projects` table — registered project repos with identity and repo metadata (see your `projects` packet stanza for the column list). Per-project structured settings live in the Project Structure aggregate: project-level test commands in the `command_definitions` family (agent-facing scopes: `quick`, `full`, `e2e`, `smoke`); deployment-flow defaults in the `deploy_defaults` family; the pre-merge verification policy in the `merge_verification` family (read by the merge engine alone, never by Tester/Engineer dispatch); per-project context routing (always-included docs and topic-keyed doc lists) in the `context_routing` family. Supporting tables: `sites`, `environments`, `project_capabilities`, `capability_templates`. Items reference projects via their project column (default `'yoke'`; cross-reference: see your `items` packet stanza).
- **Project Structure aggregate:** `project_structure` table — the unversioned policy-family declaration of project-wide structure (`areas`, `mappings`, `test_roots`, `verification_profiles`, `ownership_defaults`, `integration_targets`, `command_definitions`, `deploy_defaults`, `merge_verification`, and `context_routing`). There are no placeholder or named-only family slots. Public mutations route through `yoke project-structure patch apply`.
- **Board:** `.yoke/BOARD.md` — project-local generated board between `<!-- YOKE:BOARD:START/END -->` markers with sections for Active, Pipeline, Backlog, Freezer, and Done. Rendered by the Python board renderer (`runtime/api/board/`) via the public backlog surface. Header features dynamic emoji pixel art from `.yoke/board-art`: progress bar or random standalone art variant / rainbow fill, plus a stats box with 10-cell proportional meters. All counts use **task-expanded counting** (epics with tasks expand to N units). Below the art header, **dashboard rows** display a 14-day touched-units sparkline, an optional 90-day meter (activity, code lines, issues done, strategy lines), WIP gauge, weather indicator, type badges, age heatmap, and achievement badges.

## Execution Loop

### Single-Item Loop (conduct)

Standalone single-item execution (`/yoke conduct YOK-N`) uses the same Engineer→Tester loop per item:

1. Load task, resolve worktree path from dispatch chain
2. **Simulation gap gate** (first epic dispatch only): check plan-phase simulation for unresolved CRITICAL gaps. Blocks dispatch unless `--force`/`--ignore-gaps` is passed. Epics without simulations pass silently.
3. Verify dependencies met (`item_dependencies` hard-blocks + epic task dependencies) + interface contracts available
4. Ensure the item is in a conduct-owned executable state (`planned` / `implementing` for issues, dispatch-ready for epic tasks)
5. Invoke Engineer (implements, tests, docs, commits)
6. Invoke Tester (validates against spec, path-traces, runs project test commands and E2E against ephemeral URLs when available) — diffs exceeding 300 lines are externalized to temp files with `--stat` summaries
7. If PASS → status → `reviewed-implementation`, ready for `/yoke polish`
8. If FAIL (< max attempts) → feed Tester report to new Engineer
9. If FAIL (>= max) → status → `failed`, escalate to operator

Auto-chaining persists to DB. Survives crashes, compaction, tab closes. Continuation markers at every subagent return boundary prevent the conduct from stalling between steps 5-6 and 6-7.

## Code Conventions

- Literal zero shell. All launchers, hooks, helpers, installers, and test runners live behind `python3 -m runtime.api...` or packaged Python entrypoints. Shell is permitted only for project test commands, grep/discovery, git inspection, and diff/screenshot temp files. See `AGENTS.md` for the full contract.
- JSON: `yoke_core.domain.json_helper`. YAML: `yoke_core.domain.yaml_helper`.
- Backlog reads and writes: registered `yoke ...` commands or function-call surfaces (never direct database-client calls, never hardcoded DB paths).
