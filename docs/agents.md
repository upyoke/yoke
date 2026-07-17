# Subagent Reference

Canonical agent behavior bodies live in `runtime/agents/{agent}.md`. These are the source-of-truth persona definitions — one per agent, containing the full system prompt body. The substrate renderer fans each canonical body into per-harness adapters: Claude adapters at `runtime/harness/claude/agents/yoke-{agent}.md`, Codex custom agents at `runtime/harness/codex/agents/yoke-{agent}.toml`. The runtime `.claude/agents` and `.codex/agents` paths are symlinks into those adapter directories, so each harness reads the rendered files from its native location. Codex Desktop reads the rendered TOML adapters as custom agents and dispatches them through Codex-native primitives. Each adapter combines harness-specific metadata with the same canonical body, so the prompt text stays identical across harnesses. Claude adapters carry Markdown YAML frontmatter (`name`, `description`, `tools`, `model`, `hooks`); Codex custom agents carry the current Codex subagent schema — required `name` / `description` / `developer_instructions` plus optional config (`model`, `sandbox_mode`) that Codex inherits from the parent session when omitted. The Claude `tools` allowlist and `model` pin are Claude-only and are not emitted into the Codex TOML. The `canonical_agents` entries in `runtime/harness/bootstrap-spec.json` and `runtime/harness/codex/manifest.json` document where the canonical bodies live without inlining them into bootstrap output. Shared dispatch descriptors emit one task envelope per agent and feed both harness call paths, so phase files name agents by descriptor rather than hardcoding Claude's `subagent_type`. The drift check `HC-agent-canonical-drift` in doctor verifies adapter bodies stay in sync with their canonical sources. The full universal-source + per-harness-renderer model is documented in [`harness-substrate.md`](harness-substrate.md).

> **Note:** Shepherd and Conduct are orchestration skills (`SKILL.md` files), not agents. They run inline in the main session and invoke the 7 agents below as needed. Usher is also a skill (post-merge pipeline), not an agent. See [lifecycle.md](lifecycle.md) for the canonical state machine. Per-project test-surface docs live in each managed project at `.yoke/test-inventory.md`.

### Lane Reversal

Lane reversal preserves one canonical prompt body. Whichever harness owns a lane, the adapter file is generated from the same `runtime/agents/{agent}.md` source. Claude dispatches the Architect through `runtime/harness/claude/agents/yoke-architect.md` (surfaced as `.claude/agents/yoke-architect.md` via symlink); Codex dispatches the same Architect through `runtime/harness/codex/agents/yoke-architect.toml` (surfaced as `.codex/agents/yoke-architect.toml`). Both adapters carry the identical body from `runtime/agents/architect.md`. The shared dispatch descriptor module names the agent by descriptor, so `/yoke refine`, `/yoke conduct`, and any future lane reversal continue working without per-harness branches in skill prose. The moving parts are the adapter surface and the lane owner — not the persona text.

## Shared Prompt Doctrine

Yoke uses a shared prompt doctrine across agents and skills. The canonical source is [prompt-philosophy.md](prompt-philosophy.md).

The headline idea is `Be the giant`: we stand on inherited shoulders and owe the next agent a leg up. In practice, that means every prompt surface should leave cold-start-complete context rather than forcing the next reader to re-investigate the basics. It also means live code and current-state docs must be codebase-reader complete: assume future readers cannot see the ticket, strategy doc, plan, phase, task, or acceptance criterion that produced the change, and name every live surface by its current function, purpose, and mechanics.

## Agent Summary

| Agent | File | Model | Max Turns | Permission Mode | Tools | observe-tool |
|---|---|---|---|---|---|---|
| Product Manager | `yoke-product-manager.md` | opus | 300 | default | Read, Grep, Glob | Yes |
| Product Designer | `yoke-product-designer.md` | opus | 300 | default | Read, Grep, Glob | Yes |
| Architect | `yoke-architect.md` | opus | 300 | default | Read, Grep, Glob, Bash | Yes |
| Engineer | `yoke-engineer.md` | opus | 300 | bypassPermissions | Read, Write, Edit, Bash, Grep, Glob | Yes |
| Tester | `yoke-tester.md` | opus | 300 | default | Read, Grep, Glob, Bash | Yes |
| Simulator | `yoke-simulator.md` | opus | 300 | default | Read, Grep, Glob, Bash | Yes |
| Boss | `yoke-boss.md` | opus | 300 | default | Read, Grep, Glob, Bash | No |

## Product Manager

**Tools:** Read, Grep, Glob (no Write, Edit, Bash)
**Hooks:** PreToolUse(all tools) -> observe hook (PreToolUse), PostToolUse -> observe hook with `agent=product-manager`, PostToolUseFailure -> observe hook with `agent=product-manager`, SubagentStop -> `yoke_core.domain.agent_stop`

Single-pass spec generator. Receives feature description + codebase context + user clarifications. Cannot interact with users (subagent). Infers what it can, flags genuinely ambiguous decisions in "Open Questions" section. Outputs structured spec with: problem statement, users, goals, non-goals, functional/non-functional requirements, user stories, technical considerations. The spec is written to the item's structured fields and then read back through the rendered item body.

**Key rules:**
- PM is invoked during shepherd's `refined_idea_to_planning` transition as a prerequisite gate when the spec lacks required PRD sections. PM never asks questions -- it generates the best spec from available input.
- **Never replace existing rendered item content.** If the item's structured spec fields or rendered body already contain substantive operator notes, PM must enrich them (fill gaps, add sections, clarify) rather than rewrite from scratch. The operator's structure and decisions take precedence over PM's template.

## Product Designer

**Tools:** Read, Grep, Glob (no Write, Edit, Bash)
**Hooks:** PreToolUse(all tools) -> observe hook (PreToolUse), PostToolUse -> observe hook with `agent=product-designer`, PostToolUseFailure -> observe hook with `agent=product-designer`, SubagentStop -> `yoke_core.domain.agent_stop`

Optional phase. Produces UX spec from item spec + existing UI patterns. Outputs: user flows, screen/component specs, interaction patterns, accessibility requirements, existing patterns to reuse. Recommends skipping for non-UI work. The invoking workflow stores design output in the item's `design_spec` structured field.

**Key rules:**
- Never replace existing rendered item content. If the item's structured spec/design content already contains substantive operator decisions, the Designer must enrich it rather than rewrite from scratch.
- Output goes to `items.design_spec`, not the filesystem. The invoking workflow owns the structured-field write.

## Architect

**Tools:** Read, Grep, Glob, Bash (no Write, Edit)
**Hooks:** PreToolUse(Bash) -> `yoke_core.domain.lint_db_cmd` (legacy stable check id `lint-sqlite-cmd`) + observe hook (PreToolUse), PreToolUse(Write/Edit/Read) -> observe hook (PreToolUse), PostToolUse -> observe hook with `agent=architect`, PostToolUseFailure -> observe hook with `agent=architect`, SubagentStop -> `yoke_core.domain.agent_stop`

The most critical review gate. Produces three artifacts:
1. `technical_plan` structured field on the item
2. `epic_tasks` / `epic_task_files` rows with DB-backed task bodies and file manifests
3. `worktree_plan` structured field on the item

**Hard constraints enforced:**
1. Session-fit sizing (XS/S/M/L, never XL >100k tokens)
2. Worktree independence (no cross-worktree file overlap)
3. Sequential within worktree, parallel across worktrees
4. Tests, docs, and interface contracts mandatory
5. FR-to-task traceability matrix (every FR mapped to task(s) in `### FR Traceability` section)
6. Epic size limit (~20 tasks, propose split if exceeded)
7. All DB access goes through registered `yoke ...` commands or a registered Yoke function -- never direct database-client calls
8. Exact downstream consumer identification for every interface
9. One-direction data flow (DB is source of truth, .md files are generated views)
10. Cross-Script Contracts -- when a task adds subprocess calls, it must document the environment variable propagation pattern
11. Documentation File Checklist -- tasks that change behavior must update the relevant docs
12. Read-tool size discipline -- never read entire large files; use offset/limit
13. File discovery -- exclude noise directories from Glob/Grep

**Task metadata fields:**
- `worktree` — target worktree/branch assignment (for example `YOK-N`)
- `context_estimate` — expected task size (`XS`, `S`, `M`, `L`)
- `dependencies` — `none` or a comma-separated list of prerequisite task numbers

### Fix Mode

The Architect can also operate in **fix mode**, where it revises existing task specs based on a simulation gap report rather than creating them from an item spec. Fix mode is invoked by the `/yoke simulate` command's auto-fix flow -- it is not triggered directly by users.

**Trigger:** Fix mode activates when the invoking prompt contains a gap report and the phrase "Fix mode". This is a prompt-based trigger, not a configuration setting.

**Inputs:** The gap report (from plan or integration simulation), the rendered item body / structured plan fields (contains spec + `technical_plan`), the `worktree_plan` field, and all task specs from the `epic_tasks` DB table.

**Outputs:** Modified task files (full content, each preceded by a file-path header like `### tasks/001.md`), modified `worktree-plan.md` (full content, preceded by `### worktree-plan.md`), and a change summary table with columns: Gap #, Severity, File Modified, Change Description.

**Process:**
- Parse each gap from the report (severity, tasks involved, root cause, fix guidance)
- For `[CRITICAL]` and `[WARNING]` gaps, apply the fix guidance to the relevant task files (acceptance criteria, test plans, files-touched lists, interface contracts)
- For `[NOTE]` gaps, include in the change summary but only modify files if the fix is trivial (e.g., a count update)
- Update `worktree-plan.md` if files-touched lists changed
- Re-verify the file overlap check after modifications

**Constraints:**
- Only modify files referenced in the gap report's fix guidance
- No task restructuring, splitting, or worktree reassignment
- No changes to the `technical_plan` structured field
- Skip gaps that require code changes (noted as "requires `/yoke amend`" in the change summary)
- Preserve all existing content not targeted by a gap fix

## Engineer

**Tools:** Read, Write, Edit, Bash, Grep, Glob (all tools)
**Permission Mode:** `bypassPermissions` (required for unattended dispatch)
**Hooks:** PreToolUse(Bash) -> `yoke_core.domain.lint_db_cmd` (legacy stable check id `lint-sqlite-cmd`) + observe hook (PreToolUse), PreToolUse(Write/Edit/Read) -> observe hook (PreToolUse), PostToolUse(Bash) -> observe hook (Bash PostToolUse), PostToolUse(all tools) -> observe hook with `agent=engineer`, PostToolUseFailure -> observe hook with `agent=engineer`, SubagentStop -> `yoke_core.domain.agent_stop`

Implements exactly what the task specifies. Commits incrementally. Writes progress notes to the `epic_progress_notes` DB table via `yoke workflow-item epic-progress-note append`. Progress notes auto-synced to GitHub issue comments via hook. Uses the registered reflection path for ouroboros entries so writes land on the main repo root regardless of worktree CWD.

**Key rules:**
- Implement exactly what's specified -- don't improvise
- Follow interface contracts precisely
- Commit after each meaningful unit (not at the end)
- Stay in assigned worktree
- Don't modify files outside task scope
- If blocked by missing/mismatched interface, stop and report
- Dual-path awareness: uses repo-root-aware Python owners so shared-state writes land on the main repo root even from worktrees

**Root-Cause Analysis Protocol:** When the Engineer encounters a test failure or unexpected error, it must diagnose before fixing. The protocol requires: (1) read the failing assertion, (2) trace the code path, (3) identify the discrepancy, (4) write down the root cause before writing any fix, (5) only then write the fix. This prevents multi-attempt guessing cycles.

**Large Output Handling:** The Engineer follows strict discipline around oversized outputs: capture test suite output once to a temp file and inspect it multiple ways (rather than rerunning), never pipe a live test run directly through `tail`/`head`, use `wc -l` before reading temp files, recover from Read tool token-limit failures with offset/limit parameters, and prefer targeted extraction over full reads.

## Tester

**Tools:** Read, Grep, Glob, Bash (no Write, Edit -- 3-layer enforcement)
**Hooks:** PreToolUse(Bash) -> `yoke_core.domain.lint_db_cmd` (legacy stable check id `lint-sqlite-cmd`) + observe hook (PreToolUse), PreToolUse(Write/Edit) -> block commands + observe hook (PreToolUse), PreToolUse(Read) -> observe hook (PreToolUse), PostToolUse -> observe hook with `agent=tester`, PostToolUseFailure -> observe hook with `agent=tester`, SubagentStop -> `yoke_core.domain.agent_stop`

Validates Engineer's work. Uses `write-to-main.sh` for ouroboros reflections to ensure log entries land on the main repo root regardless of worktree CWD. Process:
1. Check acceptance criteria
2. Review code changes
3. Verify interface contracts
4. **Path tracing** -- export accuracy, runtime assumptions, downstream compatibility (warnings don't affect PASS/FAIL)
4a. **Prose-only detection** -- if all changed files are `.md`, skip the test suite (regressions structurally impossible)
4b. **Project test command selection** -- use project-provided commands when available (step 4b)
4c. **E2E execution against ephemeral URL** -- runs after unit/integration tests pass (step 4c)
5. Run tests (risk-scoped selection)
6. Verify documentation
7. Produce validation report

**3 layers of Write/Edit enforcement:**
1. `tools` allowlist excludes Write/Edit
2. `disallowedTools` explicitly blocks them
3. `PreToolUse` hooks reject attempts at runtime

**Change-scope triage:** The Tester performs change-scope analysis early to determine which test suites are relevant. Changes to docs-only files skip test execution entirely. Changes to specific script domains trigger only the related test suites rather than the full suite.

**Enhanced baseline validation with trust levels:** The Tester applies trust-level-based validation intensity. Higher trust levels (e.g., well-tested scripts with existing coverage) receive lighter review, while lower trust levels (new code, complex changes) receive deeper inspection.

**Portable timeout wrapper:** The Tester uses a portable timeout mechanism for test execution that works across BSD (macOS) and GNU (Linux) environments, preventing runaway test processes from consuming the entire turn budget.

**Browser Scenario Execution:** The Tester can execute browser QA scenarios via `yoke qa browser run`. When the dispatch prompt includes browser test scenarios (from QA seeding), the Tester runs them against ephemeral or local URLs, collecting accessibility snapshots, screenshots, and pixel-diff results. Browser test failures contribute to the PASS/FAIL verdict.

**Diff externalization:** When a per-task diff exceeds 300 lines, the conduct writes it to a temp file and passes a `--stat` summary plus file path in the Tester prompt instead of inlining the full diff. The Tester reads the file directly for line-level detail. This prevents context saturation that causes timeouts and no-verdict failures on large diffs. Diffs of 300 lines or fewer are still inlined as before.

**Key rule:** Binary PASS/FAIL verdict. No conditional pass. Path-tracing warnings are informational.

**Project-aware test selection:** The Tester supports project-specific test commands injected by the Conduct. When the dispatch prompt includes a `Project Test Commands` block (with `Quick`, `Full`, `E2E`, and/or `Smoke` entries read from the project's `command_definitions` scopes — the four-tier model), the Tester uses those commands instead of file-based test discovery. This allows the Tester to validate work on any project (not just Yoke) without hardcoded assumptions about test runners or directory layout. Project commands and file-based discovery are mutually exclusive for a given test run.

**E2E vs. smoke vs. browser integration:** The `e2e` scope is a *real* end-to-end suite that exercises a deployed backend and requires `BASE_URL` injection. Browser integration tests that mock APIs (e.g., Playwright `page.route()` intercepts) live under the `full` scope, not `e2e`. Shallow real-stack checks live under the `smoke` scope and can run from both the developer shell and the deploy pipeline's smoke stage.

**E2E execution against ephemeral URLs:** For external project items with ephemeral environments, the Conduct injects an `Ephemeral URL` and an `E2E` test command into the Tester's dispatch prompt. The Tester runs E2E tests after unit/integration tests pass, injecting the URL via `BASE_URL={ephemeral_url} {e2e_command}`. Both an ephemeral URL and an E2E command must be present to proceed; if either is missing, E2E is skipped gracefully. When E2E tests fail, the Tester collects failing test names, error messages, and Playwright artifact paths (screenshots, traces, videos from `test-results/` or `playwright-report/`). E2E failures produce a **FAIL** verdict even if all unit/integration tests passed.

## Simulator

**Tools:** Read, Grep, Glob, Bash (no Write, Edit -- 3-layer enforcement)
**Hooks:** PreToolUse(Bash) -> `yoke_core.domain.lint_db_cmd` (legacy stable check id `lint-sqlite-cmd`) + observe hook (PreToolUse), PreToolUse(Write/Edit) -> block commands + observe hook (PreToolUse), PreToolUse(Read) -> observe hook (PreToolUse), PostToolUse -> observe hook with `agent=simulator`, PostToolUseFailure -> observe hook with `agent=simulator`, SubagentStop -> `yoke_core.domain.agent_stop`

Epic-level integration gap detection. Runs at two optional points:
- **Plan simulation** (after plan, before sync) -- traces planned architecture for structural gaps
- **Integration simulation** (after all tasks complete, before merge) -- traces actual code for cross-branch mismatches

**"Always Do" steps (both phases):** FR coverage preamble check, contract matching, worktree visibility, dependency ordering, environment assumptions, gap categories.
**"If Given Actual Code" steps (integration only):** Export verification against real code, naming consistency, merge sequence simulation, validation report review.

**Gap report severity levels:** `[CRITICAL]` (blocks proceeding), `[WARNING]` (should fix, not blocking), `[NOTE]` (informational). Bracket prefixes are machine-parseable.

**VERDICT-FIRST rule:** The Simulator must emit its verdict (`SIMULATION VERDICT: PASS` or `FAIL`) before the detailed gap report. This ensures the verdict is never lost to context truncation in long reports.

**Construct Verification:** The Simulator verifies that cross-task constructs (shared types, helper functions, configuration structures) are defined consistently across all tasks that reference them. Mismatches in type shapes, function signatures, or config keys between producer and consumer tasks generate `[CRITICAL]` gaps.

**Context Budget Awareness:** The Simulator follows a two-phase protocol to manage its own context window. Phase 1 (planning) inventories all files to examine and estimates token costs. Phase 2 (execution) reads files in priority order, stopping before context exhaustion. This prevents the Simulator from running out of context mid-analysis.

**Failure Path Analysis:** The Simulator traces error handling paths across task boundaries -- what happens when a shared service returns an error, when a DB query fails, or when an API call times out. Missing or inconsistent error handling across producer/consumer boundaries generates `[WARNING]` gaps.

**Recommendation Contract with Conduct:** The Simulator's gap report includes a `fix_level` classification for each gap: `spec` (fixable by Architect in fix mode), `code` (requires Engineer via `/yoke amend`), or `process` (requires human decision). The Conduct uses this classification to route fixes automatically.

**Key rule:** All DB access goes through registered `yoke ...` commands or a registered Yoke function -- never direct database-client calls. When running scripts that may call GitHub, set `YOKE_DRY_RUN=1` to prevent creating real issues/labels.

### System-Wide Simulation (Ouroboros)

The Simulator also supports system-wide consistency auditing via `/yoke simulate --system`. Instead of tracing per-epic integration paths, it audits all of Yoke's components for internal consistency -- checking 5 gap categories: stale agent references, stale SKILL.md references, cross-agent assumption mismatches, stale hook references, and rule-implementation contradictions. Auto-fix is not available for system-wide simulation.

## Boss

**Tools:** Read, Grep, Glob, Bash (no Write, Edit)
**Hooks:** PreToolUse(Bash) -> `yoke_core.domain.lint_db_cmd` (legacy stable check id `lint-sqlite-cmd`), PreToolUse(Write/Edit) -> block commands, SubagentStop -> `yoke_core.domain.agent_stop`

Quality gate agent. Reviews worker artifacts (specs, plans, designs) at pipeline transition points and produces a structured verdict: `VERDICT: READY`, `VERDICT: NOT_READY`, or `VERDICT: CAVEATS`. Used by the Shepherd to gate transitions in the item lifecycle.

**Key rules:**
- Produces exactly one verdict per invocation
- Cannot write files -- verdict is returned as text output
- Returns the verdict as text only; the Shepherd persists the `shepherd_verdicts` row after parsing. Boss must not call `shepherd verdict` itself.
- Reviews against a configurable rubric provided in the invocation prompt
- **Self-serves item body from DB** via `yoke items get YOK-N body` -- never relies on inline content from the caller's prompt, which may be stale or summarized
- **Lifecycle-aware evaluation:** Boss `scope=plan` reviews are shepherd-epic-only (`refined_idea_to_planning`, `planning_to_plan_drafted`). It should not expect epic plan artifacts when reviewing issue or bug work outside shepherd.
- **FR coverage validation:** At `scope=plan`, Boss must verify the `### FR Traceability` section exists and covers all spec FRs. Missing section or unmapped FRs trigger NOT_READY. Specs without FR-N notation get softer CAVEATS check.
- All DB access goes through registered `yoke ...` commands or a registered Yoke function -- never direct database-client calls

> **Note:** Boss does not have agent-specific `python3 -m yoke_core.domain.observe --agent ... --hook-event ...` PostToolUse telemetry in its frontmatter. Its explicit frontmatter hooks are the shell/SQL lint guard (PreToolUse/Bash), Write/Edit block hooks (PreToolUse), and `yoke_core.domain.agent_stop` (SubagentStop).

## Common Patterns

### Tool Access Tiers

- **Read-only agents** (PM, Designer): Read, Grep, Glob only. No Bash, Write, or Edit.
- **Read + Bash agents** (Architect, Boss, Simulator, Tester): Read, Grep, Glob, Bash. Write and Edit blocked by `disallowedTools` + PreToolUse hooks.
- **Full-access agent** (Engineer): All tools. `bypassPermissions` for unattended dispatch.

### Hook Coverage

All 7 agents have SubagentStop -> `yoke_core.domain.agent_stop` (sets task to "stopped" as safety net).

**Agent-frontmatter observe attribution** (PostToolUse + PostToolUseFailure -> observe hook with `--agent ... --hook-event ...`): Present on 6 agents -- Product Manager, Product Designer, Architect, Engineer, Simulator, and Tester. Boss does not add agent-specific `--agent` wiring in frontmatter.

**Agent-frontmatter `observe-tool-pre` wiring** (PreToolUse -> observe hook): Present on the same 6 agents. Boss does not add extra frontmatter wiring for this hook.

**lint_db_cmd** (PreToolUse/Bash): Present on all 5 Bash-capable agents -- Architect, Engineer, Tester, Simulator, Boss. The hook owner is `yoke_core.domain.lint_db_cmd`; telemetry/check id `lint-sqlite-cmd` remains stable for audit-history compatibility.

**Write/Edit block hooks** (PreToolUse): Present on 3 agents -- Tester, Simulator, and Boss. Architect relies on `disallowedTools` only (no runtime block hook). PM and Designer lack Bash entirely, so the block is moot.

**on-bash-complete** (PostToolUse/Bash): Present only on Engineer. Used for progress tracking of Bash command execution.

### Shared Prompt Sections

All 7 agents include the following sections in their system prompts:

- **Turn Budget Discipline:** Rules for managing the agent's turn budget -- commit incrementally, use last 10% of turns for committing partial work, final turn must include a commit.
- **Path Resolution and Disambiguation:** Canonical path resolution rules, including the instruction to always use absolute paths, never double the `yoke/` prefix, and use `$(git rev-parse --show-toplevel)` for path resolution.
- **Ouroboros End-of-Session Reflection:** All agents produce reflections answering 4 questions: problems encountered, process improvement ideas, game-changing feature ideas, and **cross-critique observations about other agents' work**. Reflections use the `---REFLECTION-START---` / `---REFLECTION-END---` delimited block format with `---BEGIN ENTRY---` / `---END ENTRY---` per observation. Categories: `problem`, `friction`, `idea`, `cross-critique`.

**DB Quick Reference (generated packet chain):** Present on the 5 Bash-capable subagents (Architect, Engineer, Tester, Simulator, Boss) and on the top-level Yoke session via the `main_agent` packet injected by `runtime.harness.bootstrap`. The section is no longer hand-authored — each canonical prompt under `runtime/agents/<role>.md` carries `<!-- YOKE:DB-PACKET role=<role>_agent topic=T start --> ... <!-- YOKE:DB-PACKET end -->` marker pairs that `yoke_core.domain.agents_render` expands at render time using `yoke_core.domain.schema_api_context`. The expander reconciles the curated seed (the facade `yoke_core.domain.schema_api_context_seed` plus its sibling data modules `schema_api_context_tables` and `schema_api_context_commands`) against live schema introspection and CLI `--help` surfaces, so the packet stays current with schema changes. The `agents.render.check` function id (CLI adapter: `yoke agents render check`) rejects rendered adapters whose body has drifted from the freshly generated packet, malformed marker pairs in canonical prompts, seed/live schema disagreements, and stale hand-authored DB/API examples that coexist with packet markers in canonical bodies. Topics today: `core` (control plane + structured fields plus item-dependency wrappers — `epic_tasks`, `epic_progress_notes`, `events`, `shepherd dependency-{list,add,update,remove}`), `claims` (`harness_sessions`, `work_claims`, `path_claims`, `who-claims` recipe), `qa` (`qa_requirements`, `qa_runs`, QA discovery + reviewed-implementation gate preview), and `project` (`project_structure` aggregate + `command_definitions` wrappers).

**Layer-explicit packet names.** Every LLM-facing packet role uses an `*_agent` suffix so the audience layer is unambiguous:

- `main_agent` — the top-level Yoke session running inline skills / ad-hoc investigation. Receives `core` + `claims` + `qa` via `runtime.harness.bootstrap_packets` so main-session DB/API work has live packet truth alongside subagent dispatches. `qa` is included because conduct / polish / advance main sessions orchestrate engineer + tester loops and routinely inspect tester-review state (`qa_requirements` / `qa_runs` joined on `qa_kind='implementation_review'`) ahead of re-dispatch; without it the main session confabulates plausible `epic_*`-shaped names that do not exist.
- `architect_agent`, `engineer_agent`, `tester_agent`, `simulator_agent`, `boss_agent` — the five Bash-capable subagents. The marker pair role attribute in each canonical prompt uses these names; the renderer expands them via `schema_api_context.render_topic_packet`.
- `harness_contract` — the substrate manifest contract documented in [`docs/harness-bootstrap.md`](harness-bootstrap.md) and [`runtime/harness/manifest-schema.md`](../runtime/harness/manifest-schema.md). Substrate capability truth (hooks, env / session identity, cwd binding, adapter render format, supported commands, parity limits). `harness_contract` is deliberately NOT a `schema_api_context` role; it lives in the manifest layer, not in the LLM-facing packet layer.

**Per-role topic assignment (`ROLE_TOPICS`):**

- **`engineer_agent`** and **`tester_agent`** receive every topic — `core`, `claims`, `qa`, `project`. They run tests, record QA verdicts, and read project test commands at execution time.
- **`main_agent`** receives `core` + `claims` + `qa`. The QA topic is included because conduct / polish / advance main sessions orchestrate engineer + tester loops and routinely inspect tester-review state ahead of re-dispatch — the canonical surface is `qa_runs` joined to `qa_requirements WHERE qa_kind='implementation_review'`, and without it the main session confabulates plausible `epic_*`-shaped names that do not exist. `project` is still omitted: the main session reads project metadata indirectly through the items it touches and does not invoke `command_definitions` directly.
- **`architect_agent`**, **`simulator_agent`**, and **`boss_agent`** receive `core` + `claims` only. The omission of `qa` is deliberate: Architect plans the work, Simulator traces cross-task contracts, and Boss reviews specs/plans/designs in scopes that do not record QA runs themselves — adding the QA gate-preview recipes to their packet would be noise, not signal. The omission of `project` follows the same logic: those roles read project metadata indirectly through the items they touch and never invoke `command_definitions` directly. If a future role assignment needs the omitted surfaces, add the role key to `seed.ROLE_TOPICS` plus marker pairs in the canonical prompt; do not hand-author a parallel cheat sheet.

PM and Designer do not have this section because they have no Bash tool and cannot run DB queries. The invariant is that **Bash-capable actor implies packet-capable actor** — when those roles eventually gain Bash, adding their role keys to `ROLE_TOPICS` plus marker pairs in their canonical prompts is sufficient; no parallel hand-authored cheat sheet should ever be reintroduced. The current Yoke design keeps Product Manager and Product Designer non-Bash — their tool grant is `Read, Grep, Glob` only, and orchestrators pass them backlog/spec context through dispatch prompts.

**The reviewed-implementation gate is the authority — passing tests are not.** The Engineer and Tester packet now teaches `yoke qa gate-summary --item PREFIX-N --target reviewed-implementation` as the preview (or `--epic-id E --task-num K` for an epic task), and instructs that the only sanctioned way to advance to `reviewed-implementation` is through `/yoke advance YOK-N reviewed-implementation`. Direct status writes are rejected by the gate even when the test suite is green.

### CLI Prohibition

All 5 Bash-capable agents (Engineer, Tester, Boss, Simulator, Architect) include a prominent `**CRITICAL: NEVER invoke claude as a CLI/Bash command**` rule in their system prompt. This is a belt-and-suspenders defense alongside Check 5 in `yoke_core.domain.lint_db_cmd` (legacy stable check id `lint-sqlite-cmd`), which blocks local `claude` CLI invocations at the hook level. Nested Claude Code sessions crash the parent process. The only configurable exception is the project-local `lint_db_cmd_remote_claude_cli=warn` setting for operator-attended remote SSH smoke tests; local `claude` remains blocked. The Shepherd and Conduct SKILL.md files also include this rule for inline execution.

### Ticket Creation Convention

All new backlog items must go through `/yoke idea`. This is the canonical entry point for ticket creation -- it handles duplicate search, user confirmation, GitHub sync, and body updates. No skill or agent should call lower-level create adapters directly from ad hoc tooling.

**Yoke-owned noninteractive filing:** Bulk import, curate, and conduct simulation-gap filing are workflow-owned exceptions to the interactive prompt shape, not agent-facing create surfaces. They must carry explicit sanctioned intake provenance (`YOKE_IDEA_INTAKE=1` or the equivalent `--idea-intake` / `provenance="idea"` signal), pass project scope explicitly when needed, and write a full body immediately. Ad hoc sessions and dispatched agents still file through `/yoke idea` or report the discovered work to a parent session.

**Subagent guidance:** Dispatched subagents that cannot invoke `/yoke idea` (e.g., Engineer, Tester, Simulator) should report discovered issues in their structured output (reflections, progress notes, or final response). The parent session (Conduct or main session) is responsible for filing tickets via `/yoke idea` on behalf of the subagent.

**Enforcement:** The `idea/SKILL.md` dedup search runs before every ticket creation. The AGENTS.md `## Code Conventions` section documents this rule so all agents internalize it via their standard context loading.

### Turn Ceiling and Main-Session Execution

Agents invoked as subagents (via the Agent tool) are subject to their configured `maxTurns` ceiling (300 for all Yoke agents). Conduct and Shepherd now run inline via their SKILL.md files in the main session, which has no turn ceiling. Engineer enters submission mode at 30 turns remaining.

### Ouroboros Reflection

All 7 agents have an `## Ouroboros -- End-of-Session Reflection` section at the bottom of their system prompt. This is part of Ouroboros -- Yoke's self-improvement system.

**How it works:**
- Each agent answers 4 reflection questions at session end: problems encountered, process improvement ideas, game-changing feature ideas, and cross-critique observations about other agents' work
- **All agents use hook-captured reflection semantics.** Each agent includes reflections in its final response using `---REFLECTION-START---` / `---REFLECTION-END---` delimiters with `---BEGIN ENTRY---` / `---END ENTRY---` blocks inside. The PostToolUse Agent-tool hook (`packages/yoke-core/src/yoke_core/domain/reflection_capture_hook.py`) captures these blocks automatically when the subagent's `Agent` tool call returns and persists them to `ouroboros_entries`. No agent writes directly to the DB.
- **`yoke/ouroboros/log.md` has been removed** — all observations go to the DB via the hook-captured reflection surface.
- `/yoke curate` reads from the `ouroboros_entries` table -- clustering, ticketing, archiving, and promoting patterns
