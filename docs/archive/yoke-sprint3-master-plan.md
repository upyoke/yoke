# Yoke — Sprint 3 Master Plan
## *Run It For Real*
*March 2026*

---

> **SPRINT THEME**
>
> Sprint 2 built the pipeline. Sprint 3 runs it for real.
>
> One Buzz item goes from idea to `deploy_stage=complete` with E2E green. Every failure along the way becomes a Yoke ticket and gets fixed in-sprint. In parallel: hard project isolation boundaries and full observability land, so the lessons from the Buzz run embed themselves into a system that's genuinely general — not a Buzz+Yoke special case. The sprint closes with a documentation pass that records everything that actually happened, not what was planned.

---

## 1. Success Criteria

The sprint is done when all three of these are true simultaneously:

- A real, product-meaningful Buzz item reaches `status=done, deploy_stage=complete` — not a toy change, something that matters
- Playwright E2E tests ran green against a live ephemeral environment as part of that item's conduct session
- Yoke's logs tell the full story: every agent action, every state transition, every deployment event is attributed to the correct project and queryable after the fact

---

## 2. Known Gaps Entering Sprint 3

These are confirmed broken before the sprint starts. They are not discoveries — they are the opening move.

### Gap 1 — docker-compose port overrides not implemented *(blocker)*

YOK-566 is marked done, but **docker-compose.yml in ~/buzz still has hardcoded ports.** The ephemeral workflow `buzz-ephemeral.yml` already expects `API_PORT` and `WEB_PORT` to work — it calculates dynamic offsets and passes them to `docker compose up`. Until Buzz's docker-compose.yml uses `${API_PORT:-8000}` and `${WEB_PORT:-3000}`, no ephemeral environment can ever spin up at a non-production port. This is the first thing the sprint fixes.

### Gap 2 — Pipeline never run end-to-end *(unknown unknowns)*

GitHub Secrets are set, workflow files are committed, the bootstrap ran. But the full conduct → ephemeral env → tester → usher (merge + deploy) → production pipeline has never executed on a real Buzz item. There will be more failures. The sprint budget includes fixing them.

### Gap 3 — Project isolation is incomplete *(systemic)*

**YOK-664** is ready but not yet conducted. Board rendering, conduct dispatch, doctor health checks, wrapup reports, and GitHub sync all have partial or missing project scoping. Running a Buzz item will surface specific instances of this — the sprint hardens the boundaries before those gaps cause confusion.

### Gap 4 — No observability *(flying blind)*

**YOK-407** (Structured Logging) and **YOK-431** (Event Registry) are planned/ready but frozen. Without them, when something goes wrong in the pipeline, Yoke has no structured record of what happened. The sprint unfreezes them and ships them before the first full Buzz conduct session runs — not after.

### Gap 5 — Documentation lags reality *(accumulated drift)*

Sprint 2 made large changes: GitHub Actions deployment model, ephemeral environments, multi-project DB schema, new scripts, cancelled executor scripts, corrected flow definitions. The docs — including VISION.md, README.md, and the master plan — were partially updated but not fully reconciled. The sprint closes this gap with a dedicated documentation epic conducted last, once the code work is done and reality is settled.

---

## 3. Sprint Epics & Items

| Epic / Item | Title | Priority | Status |
|---|---|---|---|
| YOK-664 | Full Project Isolation | High | **done** (completed Sprint 3) |
| YOK-407 | Structured Logging — Yoke Telemetry | High | **done** (completed Sprint 3) |
| YOK-431 | Event Registry + Enforcement | High | **done** (completed Sprint 3) |
| NEW-1 | docker-compose port override fix (Buzz) | High | file → conduct |
| NEW-2 | First real Buzz item (product-meaningful) | High | file → done |
| NEW-3+ | Pipeline gap tickets (from live run) | Mixed | emerge in-sprint |
| Onboarding spec idea | /yoke onboard (spec only — no build) | High | **frozen** (spec written, parked for Sprint 4) |
| DOC | Documentation refresh (Sprint 3) | High | file → done (issue) |

---

## 4. Epic Detail

### 4.1 YOK-664 — Full Project Isolation

Enforce strict project scoping across the entire Yoke system so Buzz and Yoke state never bleed into each other. 9 tasks, single worktree.

**Why now:** Running a Buzz conduct session against a system with partial project scoping will produce confusing, hard-to-debug failures. Better to harden the boundaries first than to instrument failures caused by missing project context.

**Scope:**
- Data layer: `insert_item()` and `cmd_add()` accept `--project` and `--deployment-flow`; cross-project flow assignment rejected at creation time
- Query layer: `query-items.sh` gains `--project` filter
- Board and dashboard: all COUNT queries scoped to `default_project`
- GitHub sync: `sync-helper.sh` and `gh-issue.sh` pass `-R <github_repo>` for each item's project
- Compose/idea/standup: RESEARCH and ARRANGE phases filter by project; `/yoke idea` prompts for project and flow selection
- Health checks: NULL-project items, item-flow project mismatch, cross-project sprint integrity

> **⚠️ Critical path: Task 005**
>
> Task 005 (done-transition.sh project-aware branch lookup) is the most consequential fix in this epic. It resolves the YOK-662 regression where a Buzz branch was silently reported as "not found locally" → "already merged" → merge skipped — because `done-transition.sh` was looking for the branch in the Yoke repo instead of the Buzz repo. **This fix is a prerequisite for the Buzz pipeline run being reliable.** YOK-664 must be merged before any Buzz conduct session begins.

**Pre-conduct caveat resolutions required:**
1. FR-7 deployment_flow validation logic — move to Task 001 scope (creation-time guard), remove from Task 005
2. standup/SKILL.md — add to Task 006 file manifest and add a corresponding AC, or explicitly drop from FR-5
3. yoke-db.sh routing — note in Task 001 spec that `items add` routing needs `--project`/`--deployment-flow` passthrough

**Out of scope:** `/yoke onboard` generalization (onboarding spec idea, Sprint 4), UI-level project switching

---

### 4.2 YOK-407 — Structured Logging Standard

Establish `emit-event.sh`, the `agent_events` table, and `yoke-db.sh events` as the canonical way every Yoke agent and script records what it did.

**Why now (not Sprint 4):** The Buzz pipeline run will generate a stream of deployment events, agent decisions, and status transitions across two projects. Without structured logging, if something goes wrong there's no way to replay or audit the session. This is the sprint where observability is most needed — so it ships before the pipeline runs.

**Scope:**
- `emit-event.sh` — thin emitter: `--name`, `--project`, `--item`, `--detail`, writes a row to `agent_events`
- `yoke-db.sh events` — CRUD wrapper; query by project, item, name, date range
- `agent_events` table — schema: `id, project, item, name, detail (JSON), emitted_at`
- Call sites: conduct (item start/complete/fail), engineer (commit), tester (pass/fail), usher (merge start/complete, each deploy stage transition)
- Doctor HC: detect agents not emitting expected lifecycle events for items they touched
- Board: event count badge on active items

---

### 4.3 YOK-431 — Event Registry + Enforcement *(issue)*

Builds the governance layer on top of YOK-407: an authoritative catalog of valid event names, validation that emitted names are recognized, detection of rogue or stale events.

**Type:** issue — single worktree, single engineer pass. Conducts after YOK-407 merges. These two ship as a pair in the same sprint.

**Scope:**
- `event-registry.sh` — canonical event name catalog with descriptions and required fields
- `emit-event.sh` validation — warn (not block) on unknown names
- Doctor HC: event names used in call sites not in registry; registry entries with zero emissions in last N sessions
- `events.md` — generated reference showing all registered events and recent emission counts

---

### 4.4 Buzz Pipeline Validation (NEW-1 + NEW-2 + NEW-3+)

The core sprint work: actually run a Buzz item through the full pipeline and fix everything that breaks.

#### NEW-1 — docker-compose port override fix

File as a Buzz issue. Small, mechanical change: add `${API_PORT:-8000}` and `${WEB_PORT:-3000}` overrides to Buzz's `docker-compose.yml`. Run through the full Yoke pipeline — conduct, ephemeral env, tester (including Playwright against the ephemeral URL), usher (merge + deploy), production deploy. This is the unblocking prerequisite for everything else.

#### NEW-2 — First real Buzz item

After NEW-1 is done and the pipeline is proven to complete, file a product-meaningful Buzz item — something that actually improves the product, not just infrastructure scaffolding.

What makes a good first real item:
- Small enough to complete in one conduct session
- Touches application code so Playwright E2E has something meaningful to exercise
- Low risk — production-safe to deploy
- Demonstrates value: something you'd actually want in Buzz

#### NEW-3+ — Pipeline gap tickets

Every failure during NEW-1 and NEW-2 becomes a Yoke ticket, triaged and fixed in-sprint. The sprint explicitly budgets for this. The failure log is part of the deliverable.

> **Do not defer pipeline failures to Sprint 4.** If the ephemeral env doesn't spin up, fix it now. If the Usher misreads the approval state, fix it now. If Playwright can't reach the ephemeral URL, fix it now. The sprint is not done until the pipeline runs clean.

---

### 4.5 Onboarding spec idea — /yoke onboard (spec only) *(issue)*

Generalize the Buzz bootstrap pattern into a spec for what it would take to add any third project to Yoke. This sprint produces the spec — it does not build the command.

**Type:** issue — pure writing, single deliverable, no sub-tasks.

**Why spec-only:** We have two projects. Speccing it now means Sprint 4 can execute without a design phase. Building it now would be premature — the Buzz pipeline run will surface things that should inform the design.

**Deliverables:**
- Updated onboarding spec: full PRD for `/yoke onboard <project>`, phase by phase
- Every hardcoded Buzz assumption in the current bootstrap and how each gets generalized
- The 3-4 things that must be true before the command is buildable
- Park the onboarding spec idea when done

---

### 4.6 DOC — Documentation Refresh (Sprint 3) *(issue)*

All documentation updated to reflect the current state of the system after Sprint 2 (EXODUS) and the decisions made in this sprint. Filed as a single epic, conducted last so it captures what actually shipped — not what was planned.

**Type:** issue — one worktree, sequential file edits, no architect decomposition needed.

**Why last:** Docs written before the sprint runs will be wrong about the things that changed during it. The documentation epic runs after T1–T5 are merged.

**Conduct order within the epic:** Master plan retrospective first (requires reviewing Sprint 2 git history and actual DB state), then VISION.md and README.md (high-level, informs the rest), then the full docs/ pass.

#### VISION.md

Update to reflect that Yoke is now a two-project system with a live GitHub Actions deployment pipeline. The 1-month and 3-month visions should reference: ephemeral environments as the default pre-merge validation mechanism, GitHub Actions as the execution layer for external projects, and the path from two projects to N projects via `/yoke onboard`. Remove anything describing capabilities as future that are now live.

#### yoke/README.md

Comprehensive update covering: multi-project architecture (yoke + buzz as peers), the full deployment pipeline for external projects (conduct → ephemeral → E2E → usher (merge + deploy) → GitHub Actions → production), the bootstrap requirement for new projects, and the current agent/skill roster. Remove stale references to direct-execution deployment and the cancelled executor scripts.

#### yoke/docs/ — full pass

Every file in the docs directory gets reviewed and updated where needed:

- **`yoke-current-master-plan.md`** — see below, this is the most important one
- **`OVERVIEW.md`** — agent count, Usher description, project model
- **`db-reference.md`** — verify all Sprint 2 tables and columns are documented (`projects`, `deployment_flows`, `sites`, `environments`, `project_capabilities`, `capability_templates`, `ephemeral_environments`); add Sprint 3 additions (`agent_events`, event registry table)
- **`state-management.md`** — verify `merged`/`awaiting-approval`/`deploy_stage` lifecycle is accurate post-Sprint 2
- **`scripts.md`** — add `github-actions.sh`, `deploy-pipeline.sh`, `env-db.sh`, `emit-event.sh`, `yoke-db.sh events`, `event-registry.sh`, `bootstrap-project.sh`; remove or mark deprecated any references to cancelled executor scripts (`exec-deploy-command.sh`, `exec-test-suite.sh`, `exec-adaptive-e2e.sh`, `exec-ephemeral-deploy.sh`, `exec-ephemeral-teardown.sh`)
- **`agents.md`** — verify agent count and roles; Usher is a skill not an agent
- **`commands.md`** — add `/yoke usher`, `/yoke wrapup`; verify all commands reflect current implementations (note: `/yoke weave` was archived in YOK-764, consolidated into `/yoke usher`)
- **`worktree-lifecycle.md`** — add external project worktrees section (Buzz branches live in `~/buzz/.worktrees/`, not Yoke's repo)
- **`hooks.md`**, **`dedup.md`**, **`db-output-format.md`**, **`agent-conventions.md`**, **`backlog-schema.md`** — light accuracy pass; update anything that drifted during Sprint 2

#### yoke/docs/yoke-current-master-plan.md — the living record

This file is the authoritative history of Yoke's development. The update is **append-only** — earlier parts are never edited in place, preserving the audit trail. Two new parts are appended:

**PART 15 — Sprint 2 (EXODUS) Retrospective**

Written from the actual git history and DB state, not from memory. Covers:
- What shipped: YOK-617 (Usher v2), YOK-618 (Ephemeral Environments v2), YOK-619 (Tester v2), YOK-565 (Yoke API), YOK-566 (Buzz v1 validation), YOK-622 (pre-conduct amendments), YOK-628 (Buzz bootstrap), and all small items
- What changed mid-sprint and why: the GitHub Actions pivot (Yoke as intelligence layer, Actions as execution layer), the corrected `buzz-prod-release` flow stages (staging removed, smoke added), the bootstrap script requirement
- What was cancelled and why: YOK-564 (Usher v1), YOK-567 (Ephemeral v1), YOK-568 (Tester v1) — superseded, not abandoned
- Known gaps entering Sprint 3: the docker-compose port override miss, documentation drift, missing project isolation

**PART 16 — Sprint 3 (LEVITICUS) Plan**

The full contents of this sprint plan document, embedded as a master plan part. Cross-references `yoke/docs/yoke-sprint3-master-plan.md` as the source document. After this sprint completes, Part 16 gets a retrospective section appended to it following the same pattern as Part 15.

The master plan should always be readable as a complete history: what was designed, what was built, what changed, what was deferred, and what comes next. A new contributor should be able to read it top-to-bottom and understand the full arc of Yoke's development without reconstructing it from git logs.

---

## 5. Track Structure

| Track | Name | Key Items | Depends On |
|---|---|---|---|
| T1 | Observability | YOK-407, YOK-431 | None — run first |
| T2 | Project Isolation | YOK-664 | None — run first |
| T3 | docker-compose fix | NEW-1 (Buzz item) | T1, T2 — need logging + isolation before pipeline run |
| T4 | Real Buzz Item | NEW-2 (product item) | T3 complete and pipeline proven |
| T5 | Pipeline Fixes | NEW-3+ gap tickets | Emerges during T3/T4 |
| T6 | Onboard Spec + Docs | onboarding spec idea, DOC epic | T5 — runs last, captures what actually shipped |

T1 and T2 run in parallel first. T3 depends on both. T4 depends on T3. T5 runs concurrently with T4. T6 runs last — both the onboarding spec idea and the documentation epic benefit from knowing how the pipeline run actually went and what the final state of the system is.

---

## 6. Conduct Order

**Step 1 — Compose the sprint**
Resolve YOK-664 pre-conduct caveats (see 4.1). Shepherd and ready YOK-407, YOK-431, the onboarding spec idea, and the DOC epic. File NEW-1 via `/yoke idea` and shepherd to ready. Compose the sprint with all items assigned to tracks.

**Step 2 — Conduct T1 and T2 in parallel**
YOK-407 + YOK-431 on one track, YOK-664 on another. No dependencies between them. Usher both when done.

**Step 3 — Conduct T3 (NEW-1)**
docker-compose port override. Small code change, but run it through the entire pipeline: conduct → ephemeral env → Playwright E2E against ephemeral URL → usher (merge + deploy) → production deploy → smoke. Fix every failure before moving to Step 4.

**Step 4 — Conduct T4 (NEW-2)**
First real product-meaningful Buzz item. Same full pipeline. Expect it to be cleaner than Step 3 because Step 3 found the gaps. New gaps become T5 tickets.

**Step 5 — T5 (Pipeline Fixes)**
All gap tickets discovered during Steps 3 and 4. Sprint is not done until all P0/P1 gaps are fixed and the pipeline runs clean on at least one item end-to-end.

**Step 6 — T6 (onboarding spec idea + DOC epic) — last**
The onboarding spec update and the full documentation refresh both run after the pipeline work is done. Docs reflect what actually shipped. The master plan Part 15 retrospective is written from the actual git history and DB state, not from memory or this plan document.

---

## 7. Definition of Done

- At least one Buzz item has reached `status=done, deploy_stage=complete`
- Playwright E2E ran green against a live ephemeral environment for that item
- `agent_events` contains a full structured record of that item's pipeline run
- The board shows Buzz and Yoke items cleanly separated with no state bleed
- Doctor HC-60 through HC-69 (multi-project health checks) all pass
- Onboarding spec updated with full onboarding guidance and parked for Sprint 4
- All P0/P1 pipeline gap tickets are done — not deferred
- VISION.md, README.md, and all docs/ files reflect current system state
- `yoke-current-master-plan.md` has Part 15 (EXODUS retrospective) and Part 16 (LEVITICUS plan) appended

---

## 8. Explicitly Deferred

**Sprint 4:**
- `/yoke onboard` command — building it (the onboarding spec lands in Sprint 3; implementation is Sprint 4)
- Adaptive E2E (LLM-based selector repair) — simple failure → engineer fix loop is sufficient for now
- Staging environment for Buzz — whether this is a separate droplet, port-offset, or Fly.io is a Sprint 4 decision
- Automated retry logic on workflow failure — accurate state visibility first, retry intelligence later
- Failure categorization and `/yoke triage`

**Not building (explicitly out of scope):**
- A third project — two is enough to validate the multi-project model
- Background LLM activation on failure events
- Autonomous recovery flows

---

## 9. Open Questions

Decide during implementation, not before.

- **What is NEW-2?** Decide after NEW-1 proves the pipeline works. Criteria: small, application-code change, low-risk, Playwright-exercisable, product-meaningful.
- **Ephemeral env TTL:** tear down on branch delete, after N hours, or both? Decide during T3 conduct.
- **Usher polling behavior:** block-and-poll for runs < 5 min, exit-and-resume for longer. Lean toward block for smoke checks.
- **YOK-664 project context:** does `/yoke board` require a `--project` flag or does it infer from active sprint? Keep it simple — infer from active sprint, flag overrides.

---

## 10. Sprint Name Suggestion

**LEVITICUS** — the book of laws, rules, and priestly order. This is the sprint where Yoke gets its house in order: strict project boundaries, structured observability, and the system finally running clean enough to be trusted with real work.
