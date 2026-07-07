# State of Yoke — Strategic Checkpoint
**Date:** 2026-03-18
**Author:** Claude Opus 4.6 (strategic analysis agent)
**Scope:** Full system review — internal state, recent history, documentation, external landscape

---

## 1. Executive Summary

Yoke is a 24-day-old autonomous software factory that has delivered 1,467 completed work items across 8,670 commits, managing 2 projects (itself and Buzz) through an 8-agent, 12-command pipeline backed by SQLite state, Git worktrees, GitHub Issues, browser-based QA, and deployment flows. It is the most operationally sophisticated harness-neutral software delivery operating system that exists.

**Where we are:** Phase 1 (Agency mode) is ~85% complete. The full pipeline works end-to-end for both Yoke-internal and external (Buzz) items. Deployment flows, ephemeral environments, browser QA infrastructure, and the API control plane are all operational. The remaining 15% is hardening: QA execution gaps, pipeline ordering bugs, and agent instruction scaling.

**What matters most right now:**
1. The QA execution gap — browser QA requirements are seeded but not reliably executed
2. The ouroboros backlog — 1,578 unreviewed entries (51.3%) represent unclosed learning loops
3. Agent instruction scaling — SKILL.md files are outgrowing agent attention spans
4. No active sprint and a nearly empty pipeline (2 ready, 1 idea) — the system is between strategic cycles

**The strategic position is strong.** No competitor combines full lifecycle management (idea→deploy), multi-project orchestration, self-improvement loops, and 8-agent specialization. StrongDM's factory is the closest conceptual match but lacks sprint management, multi-project coordination, and deployment pipelines. The knowledge layer (48+ patterns, 42K events, 1,514 QA runs, velocity history) is compounding and unreplicable.

---

## 2. Scale and Current State

### System Inventory

| Dimension | Count |
|-----------|-------|
| Repository age | 24 days (since 2026-02-22) |
| Total commits | 8,670 (~361/day) |
| Completed items | 1,467 (task-expanded count) |
| DB items (raw) | 973 (931 done + 27 cancelled + 15 active pipeline) |
| Production scripts | 115 files, 52,359 LOC |
| Test files | 181 |
| SKILL.md files | 22 (6,642 LOC) |
| Agent definitions | 8 (2,511 LOC) |
| DB tables | 40 |
| Events logged | 42,000+ |
| QA runs | 1,514 |
| QA requirements | 1,471 |
| Deployment flows | 6 |
| Deployment runs | 7 |
| Ouroboros entries | 3,075 |
| Database size | 51 MB |
| Repo size | 484 MB |
| Projects managed | 2 (yoke, buzz) |
| Sprints completed | 19 (all closed) |
| Docs | 20 architecture documents |

### Current Pipeline State

- **Active:** 0 items (no active sprint)
- **Ready:** 2 items (YOK-896: cross-project scenario templates, YOK-897: visual regression dashboard) — both low priority
- **Idea:** 13 items (1 high-priority bug YOK-984, 12 frozen strategic items)
- **Frozen:** 12 items (deferred epics and features)
- **Done:** 1,467 items
- **Streak:** 23 consecutive days of completions

### Health Status (2026-03-18)

11 passed, 3 warnings, 0 failures:
- **HC-gh-orphan-detection:** 4 orphaned GitHub issues (cosmetic)
- **HC-task-label-drift:** 65 epic tasks with stale GitHub labels (status lifecycle migration residue)
- **HC-pending-sync-failures:** 6 failed syncs from 2026-03-17 (transient network errors)

---

## 3. What Changed Since the Last Checkpoint

The last 100 items (YOK-885 through YOK-984, spanning 2026-03-16 to 2026-03-18) reveal five dominant themes:

### 3a. Pipeline Hardening (Dominant Theme — ~35% of recent work)
The deployment pipeline received intensive surgical attention:
- **YOK-967:** Usher was merging to main *before* ephemeral-verify, making verification a no-op
- **YOK-950:** Raw `status=done` writes could bypass the entire merge/cleanup/deploy pipeline
- **YOK-982:** Deploy pipeline had no hard CI gate — could deploy while CI was still running
- **YOK-955:** Done-transition merged deployment-flow items then blocked on missing stages
- **YOK-969:** validate-composition rejected post-QA statuses that usher itself sets

**Inference:** The pipeline works but had ordering bugs that only surfaced during real multi-step deployments. The system is now self-correcting these through the ouroboros loop.

### 3b. QA Platform Maturation (~25% of recent work)
- **YOK-946 (Epic):** Browser QA execution pipeline — the major deliverable
- **YOK-984:** Dual QA seeding creates phantom checks (usher and recorder name mismatch) — open bug
- **YOK-979:** Blocking QA requirements could be waived without operator confirmation
- **YOK-977:** Conduct ephemeral-env capability check used wrong subcommand

**Inference:** QA infrastructure is built and gates are enforced, but the executor pipeline (browser-daemon.sh → step-executor.js → pixelmatch) has integration gaps. Requirements get seeded; execution doesn't always happen.

### 3c. Agent Instruction Architecture (~15%)
- **YOK-939/YOK-930:** The advance-to-active SKILL.md grew to 600+ lines; a ~130-line QA section drowned out the implementation directive, causing agents to stop after QA seeding instead of starting code
- **YOK-924:** Subagents lack CLAUDE.md column-name context, causing silent DB query failures

**Inference:** Instruction files are hitting scaling limits. As skills accrete requirements, key directives get buried. The re-anchoring pattern (YOK-543) works but is a band-aid.

### 3d. Infrastructure Reliability (~15%)
- **YOK-938:** Docker BuildKit cache corruption with no retry-with-prune recovery
- **YOK-962:** Browser substrate missing readiness checks, daemon swallowing startup errors
- **YOK-945:** Ephemeral subdomain routing operational

### 3e. Data Integrity & Safety (~10%)
- **YOK-918:** deploy-pipeline.sh set item status via raw SQL, bypassing sync
- **YOK-923:** deployment_runs allowed contradictory succeeded + failed status
- **YOK-889:** classify_file treated untracked backlog .md files as user-authored, blocking merges

---

## 4. What Yoke Is Doing Right

### 4a. Velocity Is Real and Sustained
1,467 items in 24 days. 361 commits/day average. 23-day streak. This is not a demo — this is a production system operating on real projects with real deployment targets. The velocity is evidence that the pipeline architecture works.

### 4b. Self-Dogfooding Is Total
Yoke manages its own development using its own pipeline. Every bug fix goes through shepherd→compose→conduct→usher. The system catches its own bugs (ouroboros→doctor→idea), files its own tickets, and deploys its own fixes. This creates a virtuous cycle where pipeline improvements immediately benefit pipeline development.

### 4c. The Knowledge Layer Is Compounding
- 42K+ events with structured telemetry
- 1,514 QA runs building quality baselines
- 48+ patterns in ouroboros
- 19 sprints of velocity data
- Cross-project learnings (Yoke→Buzz template propagation)

This is the moat VISION.md describes. No competitor starting fresh can replicate this accumulated operational intelligence.

### 4d. Governance Is Mature
- 7 PreToolUse lint hooks preventing bad states at write time
- PostToolUse telemetry on all 6 worker agents
- Health check system (14+ checks, daily reports)
- Event registry enforcement (no unregistered events)
- Commit guards (no implementation code on main during active sprints)

### 4e. Multi-Project Architecture Works
The control plane pattern — Yoke lives in its own repo, dispatches work to target repos — is proven with Buzz. Project-scoped sprints, per-project deployment flows, token isolation, and template-first capability management all function correctly.

### 4f. Documentation Is Comprehensive
20 architecture docs totaling 600+ KB. The docs are current (most updated within the last week) and well-organized. `db-reference.md` (117 KB) and `scripts.md` (170 KB) are particularly thorough.

---

## 5. Top 5 Flaws

### Flaw 1: QA Execution Gap (Critical)
**Observed fact:** QA requirements are seeded by the pipeline (663 QARequirementCreated events, 1,471 requirements). But browser QA scenarios are not reliably executed. Visual Buzz items (YOK-976, YOK-968, YOK-959, YOK-934, YOK-910 — all theme changes) reached "done" without browser verification actually running. The browser substrate exists (Playwright daemon, pixelmatch diff, accessibility snapshots) but the executor pipeline has integration gaps.

**Evidence:** YOK-984 (open bug) shows the naming mismatch between usher's QA seeder and the recorder, creating phantom checks that can never be satisfied. YOK-977 shows conduct using the wrong subcommand for ephemeral-env capability checks, silently skipping browser QA.

**Impact:** The QA gates exist in the DB but don't gate. Items pass through "validate" with requirements that were never checked. This undermines the entire quality assurance architecture.

**Recommendation:** Fix YOK-984 immediately. Then audit every `qa_runs` entry with `result=passed` to verify execution actually occurred. Consider adding HC-qa-execution-verification to doctor.

### Flaw 2: Agent Instruction Scaling (Structural)
**Observed fact:** SKILL.md files have grown beyond agent attention spans. advance/SKILL.md hit 731 lines. compose/SKILL.md is 1,096 lines. usher/SKILL.md is 1,042 lines. At these sizes, agents lose focus on late directives — proven by YOK-939 where agents stopped after a 130-line QA section instead of continuing to the implementation directive that followed it.

**Evidence:** The re-anchoring pattern (repeat critical directives after long sections) works (YOK-543) but doesn't scale. Every time a new requirement is added to a skill, the risk of burying existing directives increases.

**Impact:** Agent reliability degrades as the system matures. More features = more instructions = more missed directives. This is an inherent scaling problem.

**Recommendation:** Decompose large SKILL.md files into sub-skills (the pattern already exists for shepherd/). Extract discrete phases into separate files that are loaded sequentially. Each phase should be small enough that no critical directive is more than 100 lines from the top.

### Flaw 3: Ouroboros Backlog (Operational Debt)
**Observed fact:** 1,578 unreviewed ouroboros entries (51.3% of 3,075 total). The self-improvement loop is generating observations faster than they're being processed.

**Impact:** Patterns that could prevent future bugs are sitting unreviewed. The ouroboros loop is open — observations go in, but curation and promotion aren't keeping up. The session-start hook warns about this (threshold: 50), and the current count is 31x over threshold.

**Recommendation:** Run `/yoke curate` as a dedicated session. Consider automated triage — cluster entries by theme, auto-archive low-signal entries, surface only high-signal clusters for human review.

### Flaw 4: Pipeline Ordering Fragility (Architectural)
**Observed fact:** Multiple pipeline steps execute in the wrong order or bypass each other. YOK-967 (merge before verify), YOK-950 (raw status bypass), YOK-982 (deploy before CI), YOK-955 (merge then block). These are not random bugs — they reveal that the pipeline is a chain of independent scripts that don't enforce ordering constraints.

**Evidence:** 7 of the last 30 completed items were pipeline ordering fixes. The rate suggests more exist undiscovered.

**Impact:** Each ordering bug means items can reach production in states that violate the intended quality gates. The fixes are individual patches; the root cause is architectural.

**Recommendation:** Define a formal pipeline state machine with explicit transition guards. Each stage should validate that all prerequisite stages completed successfully before executing. Consider a `pipeline_transitions` table that records every stage entry/exit with validation status.

### Flaw 5: Empty Pipeline Between Sprints (Strategic)
**Observed fact:** 0 active items. 2 ready items (both low priority). 1 backlog idea (YOK-984, a bug). No active sprint. 12 frozen items. The system is between strategic cycles with no clear next batch of work queued.

**Impact:** The 23-day streak is at risk. The pipeline that produces 60+ items/day when loaded is idle. The frozen items include high-value epics (external project onboarding idea, YOK-847: documentation migration) that could be thawed.

**Recommendation:** This checkpoint should produce the next strategic cycle. Identify the top 5-7 items to thaw or create, compose into a sprint, and resume execution.

---

## 6. Critical Gaps and Risks

### Gap 1: No Formal Specification Language
Yoke's specs are freeform markdown in item bodies. As spec-driven development becomes mainstream (GitHub Spec Kit has 72.7K stars; StrongDM's NLSpec is production-proven), the lack of a structured, machine-parseable spec format is a competitive gap. Agents consume freeform specs with variable reliability.

### Gap 2: No External Event Ingestion
Everything is human-initiated via slash commands. The industry is moving to event-triggered agent workflows (Cursor Automations, Factory AI's Slack/Linear integration). Yoke has no webhook endpoint, no GitHub event listener, no monitoring-triggered workflows.

### Gap 3: No Service Mocking Layer
Yoke tests UI via browser substrate but has no mock layer for backend integrations. StrongDM's Digital Twin Universe (behavioral clones of third-party services) solves integration testing without hitting real APIs. As Yoke scales to client projects with external API dependencies, this gap becomes critical.

### Gap 4: Serial Epic Task Execution
Conduct dispatches tasks sequentially within tracks. Claude Code's Agent Teams now support true parallelism with dependency-aware unblocking (demonstrated: 16 agents built a C compiler in ~2000 sessions). Yoke's `epic_tasks.dependencies` system could leverage this for independent tasks.

### Gap 5: No Cross-Session Agent Memory
Individual agents start fresh each dispatch. Ouroboros captures system-level learning, but per-agent memory across sessions (what Cursor calls "memory tool") could improve agent performance on repeated task types.

### Risk 1: Single-Writer SQLite Contention
As Yoke scales to 5+ concurrent projects with parallel agent sessions, SQLite's single-writer model will become a bottleneck. The API layer (FastAPI as parallel consumer) is a step toward a solution, but concurrent shell script writers will eventually conflict.

### Risk 2: CLAUDE.md Complexity Creep
CLAUDE.md is already dense with rules, conventions, and constraints. As the system grows, the cognitive load on agents reading CLAUDE.md increases. The lint hooks compensate by catching violations, but the root cause is instruction surface area.

---

## 7. Documentation Drift and Knowledge Problems

### HIGH Drift Risk

| Document | Issue |
|----------|-------|
| **lifecycle.md** | Lists `defined`, `designed`, `planned` as item statuses. CLAUDE.md session rules list `idea, ready, active, blocked, stopped, review, validate, passed, release, done, failed`. Missing: `blocked`, `stopped`, `failed`. Extra: `defined`, `designed`, `planned` (possibly epic-only intermediate states). The canonical status list is contradictory between these two sources. |
| **state-management.md** | Conflates three independent state machines (item lifecycle, epic task lifecycle, deployment run lifecycle) in a single document. References a `completed` epic task status that doesn't appear in any defined status list. The cascading done-transition aggregation rule is ambiguous about when it fires. |
| **structured-logging-standard.md** | 57 KB design spec that overlaps with `event-contract.md` (18 KB). Unclear which is the authoritative contract for the current implementation. Engineers reading both will be confused about which to follow. |

### MEDIUM Drift Risk

| Document | Issue |
|----------|-------|
| **agents.md** | References `yoke-db.sh epic` directly (should be `yoke-db.sh epic`). Doesn't mention the critical "no nested claude CLI" constraint. Model routing not reflected. |
| **commands.md** | Multi-track dispatch mode under-specified. No documentation of WIP cap interaction. `prereq_tracks` column not documented in DB reference. |
| **hooks.md** | Summary table at top missing `observe-tool.sh` (PostToolUse on all workers). The hook is extensively documented later but the quick-reference is incomplete. |
| **template-drift-audit.md** | Excellent audit with 10 approved deviations (Category B), but none tracked as backlog items and no `DEVIATIONS.md` formalizing them. |

### LOW Drift Risk

| Document | Issue |
|----------|-------|
| **VISION.md** | Accurate and forward-looking. Missing: explicit "we are here" marker for current phase. |
| **OVERVIEW.md** | Current (last updated ~March 16). No stale entries detected. |
| **db-reference.md** | Comprehensive and current. Recently cleaned of deprecated columns. |
| **qa-platform.md** | Recent (March 18). Accurate but lacks troubleshooting runbook for common QA gate failures. |
| **event-contract.md** | Clear contract. Minor: `event_name` vs `event_type` distinction is subtle and could confuse engineers. |

### Multi-Perspective Analysis (Key Docs)

**For a PM reading VISION.md:**
- Clear on the 3-phase strategy but no "current state" anchor. When did Phase 1 start? When is the 1-month checkpoint measured from? A PM can't plan against floating milestones.
- The revenue model ("sell output, not tool") is clear. The pricing model is absent.

**For an Architect reading state-management.md:**
- The three interleaved state machines (item, task, deployment run) need to be decomposed. An architect designing a new feature can't tell which lifecycle applies to their work.
- The epic parent aggregation rule ("cannot become `passed` until all blocking tasks satisfied") doesn't specify where the check fires — conduct, usher, or a separate gate?

**For an Engineer reading lifecycle.md + CLAUDE.md:**
- Contradictory status lists. When implementing a CHECK constraint, which list is canonical?
- The `defined`/`designed`/`planned` states in lifecycle.md may be correct for epics going through shepherd but incorrect for issues filed via `/yoke idea`. This is never clarified.

**For an Operator reading commands.md:**
- No guidance on when to use `--track` vs `--all-tracks` vs single-item dispatch
- No failure mode documentation (dependency cycles, WIP cap exhaustion)
- No troubleshooting runbook

---

## 8. Simplify / Prune / Refactor Opportunities

### 8a. Consolidate Overlapping Docs
- **Merge** `structured-logging-standard.md` into `event-contract.md` or explicitly deprecate one. Two overlapping specs for the same system is worse than one incomplete spec.
- **Decompose** `state-management.md` into `item-lifecycle.md`, `task-lifecycle.md`, `deployment-lifecycle.md`, then a short `state-interactions.md` showing how they connect.

### 8b. SKILL.md Decomposition
The three largest skills (compose: 1,096 lines, usher: 1,042, advance: 731) should be decomposed into sub-skill files following the shepherd/ pattern. Target: no single phase should exceed 200 lines of instructions that an agent must hold in context simultaneously.

### 8c. Doctor.sh Modularization
At 5,266 lines, `doctor.sh` is the largest script. Health checks should be modularized into individual check scripts loaded by a lightweight harness, enabling parallel execution and easier maintenance.

### 8d. Template Node Modules
`yoke/templates/webapp/` contains vendored node_modules inflating repo size. These should be `.gitignore`d with `npm install` in the bootstrap step.

### 8e. Stale GitHub Label Cleanup
65 epic tasks have stale GitHub labels from the status lifecycle migration (YOK-831/YOK-926). A one-time sync script would clean this up. Consider adding label sync to the done-transition or adding a doctor auto-fix mode.

### 8f. Event Table Pruning
42K+ events and growing. No retention policy in place. YOK-784 (event pruning by retention_hours + severity) is filed but frozen. Thaw and implement before the DB grows unwieldy.

---

## 9. Competitive / Ecosystem Insights

### The Landscape (March 2026)

The AI-driven development space has exploded. Every major tool shipped multi-agent capabilities in the same two-week window. The competitive context:

| System | What It Does | Advantage Over Yoke | Yoke's Advantage |
|--------|-------------|----------------------|-------------------|
| **StrongDM Factory** | NLSpec → code via convergence loops, Digital Twin testing | Structured spec language (NLSpec), service mocking (DTU), satisfaction testing | Full lifecycle, multi-project, sprints, deployment pipelines, self-improvement |
| **OpenAI Codex** | 7-hour autonomous coding sessions | Long-running execution without session boundaries | Multi-agent specialization, QA gates, deployment flows |
| **Cursor Automations** | Event-triggered agent workflows from Slack/Linear/GitHub | External event ingestion, cross-session memory | Complete SDLC, SQLite state, governance hooks |
| **gstack** | 13 role-based Claude Code slash commands | Zero-setup, viral simplicity | Everything stateful — sprints, backlog, deployment |
| **GitHub Spec Kit** | Structured spec scaffolding for AI agents | Standard spec format (72.7K stars), ecosystem adoption | Execution — Spec Kit stops at specs; Yoke delivers deployed software |
| **Factory AI** | Enterprise Droids for coding/testing/deploying | Multi-channel (Slack, Mobile, Linear), Wipro partnership | Operator control, self-improvement loop, knowledge layer |
| **Claude Code Agent Teams** | Parallel Claude sessions with dependency coordination | Native platform parallelism, proven at scale (C compiler) | State management, quality gates, lifecycle tracking |

### Patterns to Steal (Priority Order)

1. **NLSpec-style structured specifications (StrongDM).** Formalize Yoke's spec format beyond freeform markdown. Make specs machine-parseable with structured scenarios, constraints, and acceptance criteria. This is the highest-leverage external pattern because it improves every downstream agent's input quality.

2. **Agent Teams for parallel execution (Claude Code platform).** Replace serial task dispatch in conduct with parallel execution for independent tasks. Yoke's dependency graph already identifies independent tasks — the execution model just needs to parallelize them.

3. **Event-triggered automation (Cursor).** Add webhook/event ingestion so external signals (GitHub webhook, monitoring alerts, scheduled triggers) can initiate Yoke workflows without human command entry.

4. **Satisfaction testing (StrongDM).** Supplement pass/fail QA assertions with probabilistic LLM-as-judge validation on behavioral trajectories. Yoke's tester agent could evaluate "does this feel right?" in addition to "does this pass the assertion?"

5. **Digital Twin / service mocking (StrongDM).** Build behavioral clones of external APIs for integration testing. Critical for scaling to client projects with external dependencies.

### Patterns to Reject

1. **Cloud sandboxes (Codex, Cursor, Devin).** Local-first with worktrees is superior for Yoke's single-operator model. Cloud adds latency, cost, and state management complexity.
2. **"No human reviews code" (StrongDM).** Yoke's review chain (shepherd→boss→final boss) is a strength. Removing human review gates is premature.
3. **Enterprise integration (Factory AI).** Jira/Linear/Slack integration adds complexity Yoke doesn't need in Phase 1.
4. **Stateless architecture (gstack).** SQLite state management is Yoke's core differentiator.
5. **Agent-agnostic frameworks (Spec Kit).** A harness-neutral operating layer enables deeper integration than any stateless cross-tool framework.

### What Yoke Already Does Better Than Everyone

1. **Complete lifecycle.** No other system goes from idea→spec→design→plan→execute→test→merge→deploy with full state tracking at every stage.
2. **Self-improvement loop.** Ouroboros (observe→log→curate→doctor→simulate) is unique. No competitor has a formalized self-improvement cycle.
3. **Multi-project coordination.** StrongDM manages one product. gstack manages one session. Yoke manages N projects with sprints, tracks, and per-project deployment flows.
4. **Proven velocity.** 1,467 items in 24 days on real production work. No published benchmark from any competitor approaches this sustained throughput.

---

## 10. Three Game-Changing Ideas

### Idea 1: Yoke-as-a-Service API (Phase 2 Accelerator)

**What:** Expose Yoke's full pipeline as a REST API with project-scoped authentication. A client submits an idea via API; Yoke shepherds it through spec, compose, conduct, and deploy — returning status updates via webhook. The client never sees Claude Code, shell scripts, or SQLite. They see a "software delivery service" endpoint.

**Why this is game-changing:** It decouples Yoke from the operator's terminal. Multiple clients can submit work simultaneously. The operator monitors via dashboard (vUtopia) instead of running slash commands. This is the Phase 2 transition from "tool I use" to "service I sell."

**Grounded in reality:** The FastAPI service already exists at localhost:8765. The DB schema already supports multi-project isolation. The deployment flow system already handles per-project configuration. The gap is auth (API keys per client), webhook notifications (status change → POST to client URL), and the idea submission endpoint.

**Estimated scope:** Medium epic (8-12 tasks). Auth + webhook + idea endpoint + client project provisioning + dashboard read views.

### Idea 2: Convergence-Tested Specifications (StrongDM Pattern Adapted)

**What:** Before a spec exits shepherd, run it through a convergence test: dispatch a lightweight engineer agent to implement the spec in a throwaway worktree, then dispatch a tester to verify. If the implementation converges (tests pass, no ambiguity-driven decisions), the spec is validated. If it diverges (agent asks clarifying questions, makes assumptions, or fails), the spec is refined.

**Why this is game-changing:** The #1 cause of wasted conduct cycles is ambiguous specs that generate incorrect implementations. Convergence testing catches this *before* sprint planning, not during execution. StrongDM proved this pattern at production scale.

**Grounded in reality:** Yoke already has throwaway worktrees, engineer/tester agent dispatch, and structured output parsing. The convergence test is a shepherd sub-step that reuses existing infrastructure. The cost is one extra agent session per spec; the savings are multiple conduct retries avoided.

**Estimated scope:** Small-medium epic (5-8 tasks). Shepherd sub-step + convergence harness + pass/fail criteria + spec refinement loop.

### Idea 3: Active Pattern Propagation (The Factory Improving the Factory)

**What:** When ouroboros curate identifies a high-confidence pattern (e.g., "agents consistently fail when SKILL.md exceeds 600 lines"), automatically generate an improvement ticket targeting the specific files, rules, or agent prompts that would prevent recurrence. The system literally files its own improvement tickets based on empirical failure data.

**Why this is game-changing:** Currently, ouroboros observations require human review to become actionable. Active propagation closes the loop: observe→curate→promote→ticket→implement→verify. The factory improves the factory using the factory. VISION.md already describes this as a 1-year goal — the infrastructure to do it exists now.

**Grounded in reality:** Ouroboros entries have structured metadata (source, category, severity). Curate already clusters by theme. The missing step is automated ticket generation (call `/yoke idea` with the pattern as spec) and automated SKILL.md/CLAUDE.md modification proposals.

**Estimated scope:** Medium epic (6-10 tasks). Pattern-to-ticket pipeline + confidence threshold + modification proposal generator + safety gate (human approval before SKILL.md changes).

---

## 11. Top 10 Priorities in Recommended Sequence

| # | Priority | Item | Type | Rationale |
|---|----------|------|------|-----------|
| 1 | **Fix YOK-984** | Dual QA seeding phantom checks | Bug fix | Blocks merge pipeline validation. Highest-severity open bug. |
| 2 | **Curate ouroboros** | Process 1,578 unreviewed entries | Operational | 31x over threshold. Unclosed learning loops degrade system intelligence. |
| 3 | **Decompose large SKILL.md files** | advance, compose, usher → sub-skills | Refactor | Agent attention scaling is a structural blocker for all future feature work. |
| 4 | **Add HC-qa-execution-verification** | Doctor check for QA runs without actual execution | New feature | Catches the QA gap (Flaw 1) systematically rather than per-bug. |
| 5 | **Reconcile status vocabularies** | lifecycle.md vs CLAUDE.md vs DB constraints | Doc fix | Engineers can't build correct validation without a canonical status list. |
| 6 | **Implement event pruning (YOK-784)** | Retention policy for events table | Thaw + implement | 42K events and growing. DB will become unwieldy without retention. |
| 7 | **Revive external project onboarding idea** | Archetypes, add-ons, config | Strategic epic | Blocks Phase 1 completion. Can't scale to 3-5 projects without streamlined onboarding. |
| 8 | **Pipeline state machine formalization** | Transition guards, prerequisite validation | Architecture | Root cause fix for Flaw 4 (pipeline ordering fragility). |
| 9 | **Convergence-tested specifications** | Shepherd sub-step for spec validation | New capability | Game-changing idea #2. Reduces wasted conduct cycles. |
| 10 | **Yoke-as-a-Service API endpoints** | Auth + webhook + idea submission | Phase 2 foundation | Game-changing idea #1. The bridge from Phase 1 to Phase 2. |

---

## 12. High-Level Going-Forward Master Plan

### Phase 1 Completion (Next 2-4 Weeks)

**Goal:** Close the remaining 15% of Phase 1. Every item that enters the pipeline exits with verified QA, correct deployment, and clean state.

1. Fix YOK-984 and audit QA execution coverage
2. Curate ouroboros backlog to close learning loops
3. Decompose the three largest SKILL.md files
4. Formalize pipeline state machine with transition guards
5. Reconcile all documentation drift (lifecycle, state-management, structured-logging)
6. Revive the external project onboarding idea and deliver a streamlined onboarding flow
7. Implement event pruning (YOK-784)
8. Clean up GitHub label drift (65 stale labels)

**Exit criteria:** A new external project can be onboarded in a single session. Every item that reaches "done" has verified QA execution. No contradictory documentation exists.

### Phase 1.5: Intelligence Layer (Weeks 4-8)

**Goal:** Make Yoke demonstrably smarter with each project it operates on.

1. Convergence-tested specifications (shepherd sub-step)
2. Active pattern propagation (ouroboros→ticket pipeline)
3. Agent Teams integration for parallel task execution
4. Cross-session agent memory (per-agent learning across dispatches)
5. Structured spec format (NLSpec-inspired, machine-parseable)

**Exit criteria:** Specs that would have caused conduct retries are caught at shepherd. Patterns automatically generate improvement tickets. Independent epic tasks execute in parallel.

### Phase 2: Service Layer (Weeks 8-16)

**Goal:** Yoke operates as a service, not a terminal tool.

1. API auth (per-client API keys)
2. Webhook notifications (status changes → client endpoints)
3. Idea submission endpoint (clients submit work via API)
4. Operator dashboard (vUtopia) for monitoring all projects
5. Event-triggered automation (GitHub webhooks → Yoke workflows)
6. Third client project onboarded and delivering

**Exit criteria:** A client can submit an idea via API and receive deployed software without direct operator CLI intervention for routine items.

### Phase 3: Scale (Weeks 16-32)

**Goal:** 5-10 concurrent projects on dedicated infrastructure.

1. Session scheduler (queue-based agent dispatch)
2. Linux infrastructure (not operator's Mac)
3. SQLite → PostgreSQL migration for concurrent writers
4. Service mocking / Digital Twin capability
5. Satisfaction testing (LLM-as-judge validation)
6. Infrastructure Engineer agent (CDK, blast-radius awareness)

**Exit criteria:** Yoke runs headless on cloud infrastructure managing 5+ projects with automated scaling.

---

## 13. What I Believe Now That I Would Not Have Said at the Start of This Review

1. **The QA gap is more serious than it appears.** Before reading the data, I expected browser QA to be partially implemented. After tracing through YOK-984, YOK-977, YOK-946, and the Buzz visual items, I believe browser QA requirements are being *seeded correctly* but *executed almost never*. The gates exist in the DB but don't actually gate. This means the quality assurance architecture is partially theater — it creates the appearance of verification without the substance. This needs to be the #1 fix.

2. **The instruction scaling problem is architectural, not tactical.** I initially assumed SKILL.md bloat was a documentation issue. After seeing YOK-939's failure mode (agents stopping at a QA section instead of continuing to implementation), I believe this is a fundamental architectural constraint. Claude Code agents have a finite attention budget. Skills that exceed ~300-400 lines of dense instructions reliably lose directives. The solution isn't better writing — it's structural decomposition into smaller, sequentially-loaded phases.

3. **The ouroboros backlog represents a bigger strategic risk than any single bug.** 1,578 unreviewed entries means 1,578 potential improvements that aren't happening. Some of these entries likely describe bugs that haven't been filed, patterns that haven't been promoted, and process failures that keep recurring. The self-improvement loop is Yoke's strongest differentiator — but only if the loop is actually closed.

4. **Yoke is closer to Phase 2 than I expected.** The FastAPI service exists, the multi-project model works, deployment flows are operational, and the template system handles project provisioning. The gap to "service" is smaller than I anticipated — primarily auth, webhooks, and a submission endpoint. This is weeks of work, not months.

5. **The competitive landscape validates Yoke's architecture more than it threatens it.** Every competitor I researched does a subset of what Yoke does. StrongDM does specs→code. Codex does long autonomous sessions. Cursor does event triggers. gstack does role-based prompting. Factory does enterprise Droids. None of them combine the full lifecycle with self-improvement, multi-project coordination, and deployment automation. Yoke's risk isn't competition — it's execution speed. The window to establish the knowledge layer advantage is finite.

---

## 14. Evidence, Assumptions, and Open Questions

### Evidence Base
- **DB queries:** Direct SQL against yoke.db for item counts, event volumes, QA statistics, sprint history, ouroboros state
- **Git history:** 8,670 commits analyzed for velocity, patterns, and recent focus areas
- **Document review:** 20 architecture docs, VISION.md, PAD.md, CLAUDE.md, session rules
- **Item analysis:** Last 100 items (YOK-885–984) reviewed for themes; 25 most strategically relevant items read in full
- **Health report:** 2026-03-18 health check results (11 pass, 3 warn, 0 fail)
- **Wrapup reports:** Last 5 session wrapups for velocity and friction signals
- **External research:** 15+ external sources on Claude Code, Codex, Cursor, StrongDM, gstack, Factory AI, Spec Kit, SWE-Agent, MetaGPT, AI QA tools

### Assumptions
1. The board's count of 1,467 done items (vs DB's 931) is due to task-expanded counting where epics contribute N units (one per task). I assume this is correct behavior, not a counting bug.
2. I assume the 12 frozen items are frozen by deliberate strategic choice, not by accident or abandonment.
3. I assume the API service (localhost:8765) is functional but not yet serving external traffic.
4. I assume the browser substrate (Playwright daemon) is deployable but not yet reliably integrated with the conduct pipeline.

### Open Questions
1. **Has any Buzz item been deployed to production via the full pipeline?** VISION.md's 1-month checkpoint requires this. I could not confirm from the data whether this has happened.
2. **What is the actual browser QA execution rate?** How many of the 1,514 QA runs involved actual browser interaction vs. DB-only state changes?
3. **Why are all 19 sprints closed?** Is this normal cadence (rapid sprint cycles) or does it indicate a planning gap where work happens without sprint structure?
4. **What's the cost profile?** At 42K+ events and 8,670 commits, what's the Claude API spend? Is the velocity sustainable at current token costs?
5. **Is the FastAPI service actively running?** The code exists but I couldn't verify runtime status from the data available.
6. **What patterns are in the ouroboros that would change this analysis?** With 1,578 unreviewed entries, there may be signal I couldn't access.

---

*This memo is a strategic checkpoint, not an implementation plan. The priorities and timelines above are recommendations that should be refined through operator judgment and sprint planning.*

---

## 15. Reflections After Reading MASTER-PLAN.md

After completing this analysis, I was asked to compare my document against a parallel strategic checkpoint produced by a different model ([MASTER-PLAN.md](/Users/dev/yoke/MASTER-PLAN.md)). Here is what I learned and what I would change.

### What Altman Gets Right That Darius Misses

**1. The Central Thesis Is Sharper.**
Altman's core insight — "Yoke's biggest danger is self-deception through stale docs, duplicated contracts, partial health reporting, and ceremonial states that imply more trustworthiness than the runtime actually guarantees" — is a more penetrating diagnosis than anything in my doc. I identified the QA execution gap as Flaw #1 but framed it as a bug to fix. Altman frames it as a *systemic honesty problem*: the system has the language of verification before it has the reality. That's a fundamentally different (and more useful) framing.

**2. "Consolidation, Not Expansion" vs My Forward-Leaning Roadmap.**
My game-changing ideas (#1 Yoke-as-a-Service API, #2 convergence-tested specs, #3 active pattern propagation) are all *new capabilities*. Altman's game-changing ideas (#1 Truthfulness Console, #2 Mission Layer, #3 Project Bootstrap Contract) are all *making what exists legible and trustworthy*. Altman is right. My roadmap adds complexity to a system that's already struggling with complexity. The correct next move is subtraction, not addition.

**3. The Health Report Skepticism.**
I reported "11 passed, 3 warnings, 0 failures" as a health signal. Altman noticed that the March 8 report had *53 checks* while the March 18 report only had *14* — and correctly flagged that the apparent improvement might be an artifact of reduced scope, not actual health. I took the health report at face value. Altman questioned whether the instrument itself was trustworthy. That's better analysis.

**4. The "Knowledge Inversion" Observation.**
Altman identifies that "the newest operational reality is captured more accurately in item bodies, scripts, and recent tickets than in canonical docs" — creating a state where the repair history is more reliable than the official explanation. I catalogued documentation drift as a list of stale docs. Altman identified it as a structural inversion that undermines Yoke's value proposition of disciplined operation.

**5. "Ceremony Without Certainty."**
This phrase from Altman's section 6.1 captures something I circled around but never named. When Yoke has a schema truth, a workflow-script truth, a doc truth, and a board truth that can diverge, the ceremony (status transitions, QA requirements, deployment gates) can all be performed without producing actual certainty. I documented the individual symptoms (QA phantom checks, pipeline ordering). Altman diagnosed the disease.

**6. Tone and Judgment.**
Altman is blunter and more willing to render judgment: "not reflection; it is sediment" (on ouroboros), "make its guarantees simpler, truer, and easier to understand" (on the strategic problem), "production reality forced a burst of honesty work" (on recent history). My doc hedges more and presents more options. For a strategic checkpoint aimed at an operator/boss, Altman's directness is more useful.

### What Darius Has That Altman Lacks

**1. Quantitative Depth.** My doc has more precise numbers — exact LOC counts, event distributions, script inventories, table counts. Altman uses numbers selectively for impact. Both approaches are valid; mine is more auditable, Altman's is more readable.

**2. External Research.** My external scan (StrongDM, Codex, Cursor, gstack, Factory, Spec Kit, SWE-Agent) is substantially more detailed. Altman cites the same sources but extracts principles rather than pattern-by-pattern analysis. My treatment of StrongDM's NLSpec, Digital Twin Universe, and satisfaction testing adds genuinely new strategic options that Altman doesn't surface.

**3. The Agent Instruction Scaling Analysis.** My Flaw #2 (SKILL.md files outgrowing agent attention spans, with the YOK-939 evidence) is a structural insight that Altman doesn't address. This is a real architectural constraint that affects everything downstream.

**4. Concrete Implementation Sequencing.** My Priority #1-10 list is more actionable in terms of "what do I do on Monday." Altman's priorities are thematic ("fix canonical docs", "unify deploy and QA check naming") but less specific about which items, which scripts, which exact changes.

### What I Would Change in This Document

1. **Rewrite the executive summary** around Altman's framing: the central problem is truthfulness, not feature gaps. "Yoke's guarantees are partially ceremonial" is a more honest and more useful starting point than "Phase 1 is 85% complete."

2. **Replace game-changing ideas 1 and 2** (API service, convergence-tested specs) with Altman's Truthfulness Console and Mission Layer. My ideas are good Phase 2/3 features but they're wrong for *right now*. The system needs to earn trust in its existing guarantees before adding new ones.

3. **Add Altman's health report skepticism** to my health status section. I was credulous about the 11-pass/3-warn/0-fail report. The scope reduction from 53→14 checks is a red flag I missed entirely.

4. **Restructure the master plan** around "truthful → teachable → multipliable" instead of "Phase 1 completion → Intelligence layer → Service layer." Altman's phasing is more honest about where Yoke actually is.

5. **Add the "ceremony without certainty" risk** as a standalone section. Multiple sources of truth that can diverge is a systemic risk I documented piecemeal but never named as a first-class problem.

6. **Tone down the competitive triumphalism.** My doc says "no competitor combines full lifecycle management." That's true but it's the wrong emphasis. What matters is whether Yoke's lifecycle management is *honest*, not whether it's *unique*. Altman's framing — "the system had the language of verification before it had those guarantees wired correctly" — is more useful than "we're ahead of StrongDM."

7. **Keep my external scan and agent scaling analysis** — these are genuine additions. But subordinate them to the consolidation thesis rather than presenting them as near-term priorities.

### Bottom Line

Altman wrote a better strategic document. It identified the right central question ("is this system truthful?") rather than the obvious one ("what should we build next?"). My doc is more comprehensive and more quantitatively grounded, but Altman's is more strategically useful because it names the real problem and recommends the right response: make what exists trustworthy before building what comes next.

---

## 16. Message for Altman

*Written after reviewing the rewritten [MASTER-PLAN.md](/Users/dev/yoke/MASTER-PLAN.md), [MASTER-MAP.md](/Users/dev/yoke/MASTER-MAP.md), updated [VISION.md](/Users/dev/yoke/VISION.md), updated [OVERVIEW.md](/Users/dev/yoke/yoke/docs/OVERVIEW.md), updated [README.md](/Users/dev/yoke/yoke/README.md), and all recent commits (YOK-984 through YOK-994).*

### What You Changed (and Whether It's Right)

#### VISION.md Updates

You made five surgical edits:

**1. Added "wish engine" metaphor (line 11).** Good. The genie/wishes framing makes the compounding value proposition visceral and memorable. It's the kind of line a client presentation opens with.

**2. Added mission layer + portable skill layer to Core Strategic Bet (lines 33-40).** This is the most significant change. VISION.md now formally commits to:
- An operator-facing mission layer above commands
- A portable skill layer not trapped in one harness's prompt format
- Direct-item workflows as first-class alongside sprints
- Ad hoc planning loop as a real control surface
- Framework closure: meaningful execution either runs through a named workflow or gets captured as an explicit manual override

**Verdict:** Right direction. But there's a tension — VISION.md still says "Don't fuse orchestration logic to Claude Code's runtime" (line 214) and "Don't build your own agent harness" (line 215) simultaneously. Those were already in tension before the mission layer / portable skill additions. Now they need reconciling. The new strategy explicitly *does* plan to decouple from Claude Code (which is the spirit of item 1) and eventually may build a custom harness (Phase 6 of your plan). These items should be rewritten to reflect the evolved position — something like "Don't fuse orchestration logic to *any single* runtime" and "Don't build your own harness *before the control plane is clean and you have at least two adapter comparisons*."

**3. Added skill layer separation to API section (lines 130-144).** Notes that SKILL.md files are too harness-specific to be the final portability story, and names Vercel `skills` as a candidate substrate. **But it's duplicated** — lines 130-136 and 138-144 are identical paragraphs. Copy-paste artifact. Should be cleaned up.

**4. Added push-based ouroboros to 6-month vision (line 81).** Changed from "auto-curate after sprint close" to "auto-curate after sprint close or mission completion." Small but correct — if missions replace sprints as the default flow, the ouroboros trigger needs to fire on mission completion too.

**5. Added harness portability note to agent constraints (line 165).** "This works well for the current Claude-native system, but it should not be assumed to be the long-term portability boundary." Right. This is the honest version of the constraint.

#### OVERVIEW.md Updates

Three significant changes:

**1. Added "wish engine" and mission framing (lines 7-9).** Mirrors VISION.md. Good consistency.

**2. Rewrote the pipeline section (lines 13-34).** Now shows two first-class paths: direct item flow (`idea → optional shepherd → advance active → maybe conduct → usher`) and optional formal sprint flow. The operator update loop (ask agent for ad hoc plan) is explicitly called out. **This is a major reframe.** Previously, the pipeline was presented as a linear sequence with compose/sprint as the assumed center. Now direct-item flow is first-class and sprints are optional.

**3. Added framework closure gap (lines 17-19).** Explicitly acknowledges that "the main agent can still manually perform pieces of execution outside explicit framework ownership" and calls the desired end state: "meaningful execution should run through named Yoke workflows or be captured as manual overrides with evidence."

**Verdict:** These OVERVIEW changes are accurate to how Yoke actually operates today. The sprint-centric framing was already stale — recent work has been mostly direct-item flow without sprints. Documenting reality is the right move.

#### README.md Updates

Substantial rewrite of the intro and flowchart:

**1. Intro reframing (lines 1-9).** Now leads with "Turn your codebase into an agent-run software factory" and immediately describes the two main paths (direct item flow + optional sprint batching) with the ad hoc planning loop. Much better than the previous sprint-centric framing.

**2. Flowchart (lines 57-117).** Still shows the sprint-centric pipeline (idea → shepherd → compose → conduct T1/T2/T3 → usher → done). **This contradicts the new intro** which says sprints are optional. The flowchart should show the direct-item path as the primary flow, with compose/sprint as an optional branch.

**3. Still says "Eleven operator commands" (line 11)** but CLAUDE.md says 12. Missing `curate` from the list.

#### MASTER-MAP.md

This is the strongest new artifact. The Path A / Path B / Migration Shape structure is clean and visual. The migration strategy (observe → shadow → canary → primary → retire) is disciplined. The "NEVER DO THIS: two permanent authoritative write paths for the same concern" rule is the single most important sentence across all the planning docs.

The updated version correctly shows direct-item flow and the operator update loop as first-class paths alongside the optional formal sprint flow. The "framework leakage" annotation in the Implementation Locus box is honest and important.

#### MASTER-PLAN.md (Rewritten)

The rewrite successfully absorbs my operational corrections and the strategy session's new direction. The two most important additions since the version I previously reviewed:

**Section 2.7 + 6.8: Framework leakage / closure gap.** You correctly identified that "maybe conduct" isn't just flexible — it's a truthfulness hole. If the main agent can do parts of implementation without conduct, then the event log is incomplete, the QA pipeline doesn't fire, and the website can't show what actually happened. This is bigger than a wording problem — it's a prerequisite for everything else in the plan.

**Phase 2 expansion (lines 688-716).** Now includes framework-closure rule definition, direct-item vs batch mission distinction, and the operator-in-the-loop planning assist. This correctly handles the real complexity of Yoke's operating model rather than forcing it into a single-path abstraction.

### Issues I Found

**1. VISION.md has a duplicated paragraph.** Lines 130-136 and 138-144 are identical. Copy-paste error.

**2. README flowchart contradicts its own intro.** The intro says direct-item flow is first-class and sprints are optional. The flowchart shows sprint-centric pipeline as THE path. The flowchart needs a rewrite showing direct-item as primary with compose/sprint as an optional branch.

**3. README says "Eleven" commands, should be twelve.** Missing `curate`.

**4. README flowchart still uses `status=merged`.** Line 90: `→ status=merged`. But `merged` is retired (YOK-831). Should be `passed`.

**5. OVERVIEW still references `in_progress` status.** Line 184: "Update status → `in_progress`". Not in the canonical status list. Should be `active`.

**6. VISION.md "What to Avoid" section is now internally contradictory.** Item 1 ("Don't fuse orchestration logic to Claude Code's runtime") and Item 2 ("Don't build your own agent harness") are in tension with the new strategy that explicitly plans to decouple from Claude Code and may eventually build a custom harness (your Phase 6). These should be rewritten to reflect the evolved position.

**7. Phase 0 vs Phase 1 naming confusion.** MASTER-PLAN-ALTMAN calls truthfulness cleanup "Phase 0" and API canonicalization "Phase 1." VISION.md still uses "Phase 1" to mean "Agency mode" (managing two projects end-to-end). These are different numbering systems referencing different things.

### Where I Agree With You

**1. The sequence is right: truthful → canonical → decoupled → operator-facing → scalable.** The ordering is load-bearing. You can't build a website on a stale API. You can't add a second harness without a common mission contract.

**2. The framework-closure gap is the sleeper issue.** It's a truthfulness, observability, and portability problem all at once. If meaningful work can happen outside named workflows, the website can never be a reliable control surface.

**3. Direct-item flow as first-class, sprints as optional batch mode.** This matches reality. The last 19 sprints were rapid 1-4 day cycles, and recent work has been mostly sprint-less.

**4. Shell demotion to leaf adapters.** 296 shell scripts doing orchestration scales linearly with features. Moving business rules to the service layer and keeping shell for git/deploy edge operations is the right structural change.

### Where I'd Push Back or Add Nuance

**1. The Vercel `skills` reference needs investigation before it becomes strategy.** Both [VISION.md](/Users/dev/yoke/VISION.md) and [MASTER-PLAN.md](/Users/dev/yoke/MASTER-PLAN.md) name it as "a plausible candidate substrate" for the portable skill layer. That's fine as a hypothesis, but it's unvalidated. Before committing architecturally, we need: (a) does the format actually support Yoke's complexity? (b) does it handle multi-step orchestration or just single-shot capabilities? (c) is the ecosystem mature enough to bet on? I'd recommend a spike: port one simple skill (e.g., `idea`) to Vercel skills format and evaluate.

**2. Phase 0 should include the README flowchart fix.** The README is the most visible document. If it still shows sprint-centric flow with retired statuses, it actively misleads new sessions. It's a 30-minute fix and should be in Phase 0, not deferred.

**3. Your 12 backlog items (section 16) should become real YOK-N tickets.** Right now they're prose in a planning doc. Until they're items in the backlog, they don't exist in the system they describe. The irony of a software delivery operating system having its own roadmap outside its own backlog is exactly the kind of truthfulness gap both our docs warn about.

**4. The ouroboros backlog (1,578 unreviewed) should be addressed in Phase 0.** Both plans acknowledge it. Neither prioritizes it. But 1,578 unreviewed entries at 31x threshold means the self-improvement loop — Yoke's strongest differentiator — is effectively offline. A single curate session to cluster, archive low-signal entries, and surface the top 20 patterns would restore the loop.

**5. YOK-992/993/994 show the pipeline is still actively discovering bugs.** YOK-992 was reverted because browser QA ran against a stale ephemeral environment. YOK-993 and YOK-994 are new issues found during label sync work. The system is still in "honesty work" mode — which validates your Phase 0 thesis, but also means Phase 0 should budget for emergent bug work, not just the named doc/API fixes.

### Concrete Recommendations for Next Session

1. **Fix the VISION.md duplicate paragraph** (lines 130-144). 2 minutes.
2. **Fix README flowchart** to show direct-item flow as primary, sprint as optional branch. Fix command count (12 not 11), retire `status=merged` reference. 30 minutes.
3. **Fix OVERVIEW `in_progress` reference** on line 184. 2 minutes.
4. **Run `/yoke curate`** to process the ouroboros backlog. 1 session.
5. **File the first 5 Phase 0 items as YOK-N tickets** via `/yoke idea`. Put the roadmap inside the system it describes. The remaining 7 can follow after Phase 0 exit criteria are met.
6. **Rewrite "What to Avoid" in VISION.md** items 1-2 to reflect the evolved multi-harness strategy.

That's Phase 0, session 1. The rest follows from the sequence you already defined: truthful → canonical → decoupled → operator-facing → scalable.
