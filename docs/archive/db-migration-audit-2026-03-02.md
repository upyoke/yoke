# DB Migration Audit — Complete Findings (2026-03-02)

## Ticketed Items
- P0 body writes: YOK-317 AC-2
- P1 stale log.md refs + dead groom-state.md: YOK-328
- P2 release notes dual-write: YOK-330
- P3 non-epic reviews table: YOK-332
- 10 .md readers → DB queries: YOK-329
- 5 stale epics/ refs: YOK-331
- Dead dual-write bridge in update-status.sh: YOK-333
- Legacy file cleanup (log.md, archive/): YOK-334

---

## Context
Comprehensive investigation of whether everything in Yoke is migrated to the DB, what remains as file-only, what's a read-only generated artifact, and where the boundaries leak.

---

## 1. DB Schema Overview (18 tables)

| Table | Rows | Purpose |
|-------|------|---------|
| `items` | 325 | Core backlog — all work items (source of truth) |
| `sprints` | 10 | Sprint lifecycle (open/active/closed) |
| `tracks` | 6 | Track definitions within sprints |
| `shepherd_verdicts` | 9 | Quality-gate verdicts on status transitions |
| `composer_sessions` | 1 | Groom orchestration session state |
| `composer_operations` | 1 | Ordered changeset ops within a session |
| `conductor_progress` | 40 | Track conductor execution state |
| `deployment_events` | 0 | Deployment pipeline events |
| `ouroboros_entries` | 189 | Self-improvement observations |
| `wrapup_reports` | 23 | Session wrapup reports |
| `release_entries` | 215 | Release note entries per item/version |
| `epic_tasks` | 175 | Sub-tasks within epics |
| `epic_task_files` | 0 | File manifest per task |
| `epic_task_history` | 606 | Status transition audit log |
| `epic_dispatch_chains` | 28 | Per-worktree dispatch queues |
| `epic_reviews` | 79 | QA review verdicts |
| `epic_progress_notes` | 173 | Engineer progress notes (synced to GH) |
| `epic_simulations` | 28 | Plan/integration simulation reports |

---

## 2. Generated Artifacts (DB → File, Read-Only)

These files are generated from DB and should NEVER be edited directly:

| File | Generator | DB Tables | Fully Read-Only? |
|------|-----------|-----------|-------------------|
| `yoke/BOARD.md` | `rebuild-board.sh` | `items`, `sprints`, `epic_tasks` | **YES** — no violations found |
| `yoke/tracks.md` | `/yoke tracks` SKILL | `tracks`, `items`, `sprints` | **YES** — sole writer is `/yoke tracks` |
| `yoke/backlog/{NNN}.md` | `generate-backlog-md.sh` | `items` | **NO** — 8 SKILL.md files write directly (see §4) |
| `yoke/ouroboros/wrapups/*.md` | `ouroboros-db.sh generate-wrapup` | `wrapup_reports` | **YES** — inserted to DB first, then rendered |
| `yoke/releases/*.md` | `release-notes-db.sh generate` | `release_entries` | **MOSTLY** — `done-transition.sh` also appends directly (legacy dual-write) |

### Verdict: BOARD.md, tracks.md, and wrapup .md files are clean. Backlog .md files and release .md files have leaks.

---

## 3. Fully DB-Backed Data (No Disk Artifacts)

| Data | DB Table | Old Location | Migration Status |
|------|----------|-------------|------------------|
| Epic tasks (metadata, body, status) | `epic_tasks` | `yoke/epics/{name}/tasks/*.md` | **COMPLETE** — directory deleted |
| Epic task files | `epic_task_files` | inline in task .md | **COMPLETE** |
| Epic status history | `epic_task_history` | `yoke/epics/{name}/status/*.json` | **COMPLETE** — dual-write bridge still in `update-status.sh` but only fires when JSON exists (it doesn't) |
| Epic dispatch chains | `epic_dispatch_chains` | `yoke/epics/{name}/dispatch-chain-*.json` | **COMPLETE** |
| Epic reviews | `epic_reviews` | `yoke/epics/{name}/reviews/*.md` | **COMPLETE** for epics |
| Epic progress notes | `epic_progress_notes` | (new, no predecessor) | **COMPLETE** |
| Epic simulations | `epic_simulations` | `yoke/epics/{name}/simulation-*.md` | **COMPLETE** |
| Worktree plans | `items.body` (inline section) | `yoke/epics/{name}/worktree-plan.md` | **COMPLETE** — plan SKILL writes to body |
| Groom state | `composer_sessions` + `composer_operations` + `shepherd_verdicts` | `yoke/groom-state.md` | **COMPLETE** — file is dead weight, doctor HC-38 already flags it |
| Ouroboros entries | `ouroboros_entries` | `yoke/ouroboros/log.md` | **COMPLETE** — log.md deprecated header says so |
| Conductor progress | `conductor_progress` | (new) | **COMPLETE** |

---

## 4. Files Still Written Directly (Bypassing DB) — THE PROBLEMS

### P0 — Backlog .md body writes via deprecated auto-ingest hook

**8 SKILL.md files** instruct editing `yoke/backlog/{NNN}.md` directly, relying on `auto-ingest-hook.sh` (YOK-317, still active but deprecated) to sync back to DB:

1. `groom/compose/SKILL.md` (line 279) — spec decisions
2. `groom/advance/SKILL.md` (line 46) — body edits (offers DB-first alternative but also .md)
3. `groom/advance/SKILL.md` (line 146) — BOSS verdicts
4. `groom/materialize/SKILL.md` (line 258) — sprint caveats
5. `groom/vet/SKILL.md` (line 119) — auto-fix findings
6. `wrapup/SKILL.md` (line 146) — ouroboros entry edits to item bodies
7. `help/SKILL.md` (line 68) — "review & edit spec in .md"
8. `promote/SKILL.md` (line 80) — "review the spec in .md, edit if needed"

**Risk:** If auto-ingest hook is removed (YOK-317) before these are fixed, body edits silently vanish.

### P1 — Stale `ouroboros/log.md` references

3 SKILL.md files still reference writing to `yoke/ouroboros/log.md` (deprecated):
- `promote/SKILL.md` (line 56)
- `design/SKILL.md` (line 37)
- `merge/SKILL.md` (line 86 — git add)

### P2 — Release notes dual-write

`done-transition.sh` (lines 323-349) appends directly to `yoke/releases/*.md` via awk, in addition to inserting into `release_entries` DB table. Legacy bridge.

### P3 — Standalone issue reviews (no DB table)

`yoke-tester.md` agent writes review files to `yoke/backlog/reviews/YOK-{N}.md` for non-epic issues. Epic reviews go to `epic_reviews` table. **There is no `issue_reviews` table.** This is a gap.

---

## 5. Disk-Only Data (Never Migrated to DB)

| Data | Location | Should it be in DB? |
|------|----------|---------------------|
| **Design specs** | `yoke/designs/*.md` (3 files) | **YES** — designs belong in DB. Will need `designs` table + human-editable DB workflow. Status tracked in `items.status='designed'` but content is file-only today |
| **Ouroboros patterns** | `yoke/ouroboros/patterns.md` | **Probably yes** — sole copy, actively read by curate + doctor. No backup mechanism |
| **Health reports** | `yoke/ouroboros/health/health-*.md` (8 files) | **Probably no** — point-in-time snapshots for human consumption |
| **System simulations** | `yoke/ouroboros/health/simulation-system-*.md` | **Probably no** — asymmetric with epic simulations (which ARE in DB) but low frequency |
| **Curate session reports** | `yoke/ouroboros/curate-*.md` | **Probably no** — session artifacts |
| **Session timing logs** | `yoke/ouroboros/session-logs/` | **No** — debugging/metrics only |
| **Error logs** | `yoke/ouroboros/errors.log` | **No** — transient debugging |
| **Legacy archives** | `yoke/ouroboros/archive/*.md` | **No** — pre-migration data, preserved for history |
| **groom-state.md** | `yoke/groom-state.md` | **No** — already replaced by DB, delete it |

---

## 6. Who Reads backlog/*.md vs Querying DB?

### Reads .md files (SHOULD query DB instead)

| # | Reader | File | What it reads from .md | Should read from |
|---|--------|------|------------------------|------------------|
| 1 | `/yoke curate` | `curate/SKILL.md` lines 63, 77 | ALL item titles + bodies (frontmatter + body) for duplicate detection | `yoke-db.sh items list` + `items get N body` |
| 2 | `/yoke dispatch` | `dispatch/SKILL.md` line 200 | Full item spec to pass to Engineer subagent | `yoke-db.sh items get N body` |
| 3 | `/yoke release-notes` | `release-notes/SKILL.md` line 31 | All done items' bodies for categorization | `yoke-db.sh items list --status done` + body query |
| 4 | `/yoke groom vet` | `groom/vet/SKILL.md` line 20 | Full item spec for quality vetting | `yoke-db.sh items get N body` |
| 5 | `yoke-final-boss.md` | Agent def lines 36, 47 | ALL sprint item bodies for GO/NO-GO verdict (already queries DB for item *list* but reads bodies from .md!) | `yoke-db.sh items get N body` per item |
| 6 | `doctor.sh` HC-21 | Script lines 1113-1146 | All item bodies for bug-adjacent language scan | `yoke-db.sh query "SELECT id, body FROM items WHERE body IS NOT NULL"` |
| 7 | `/yoke plan` | `plan/SKILL.md` line 53 | Item body/spec as planning input — hedges "from DB or .md" | Remove .md alternative, keep DB-only path |
| 8 | `/yoke wrapup` | `wrapup/SKILL.md` line 144 | Item bodies to update with ouroboros entries | `yoke-db.sh items get N body` |
| 9 | `/yoke promote` | `promote/SKILL.md` line 76 | Item spec for review before promotion | `yoke-db.sh items get N body` |
| 10 | `rebuild-board.sh` | Script line 373 | `epic` frontmatter field from worktree branch via `git show` | **Hardest to fix** — branch may have data not yet in DB. Needs design decision. |

### Already reads from DB (correct pattern)

`/yoke backlog`, `/yoke standup`, `/yoke stats`, `/yoke simulate`, `/yoke design`, `/yoke next`, `/yoke import`, `/yoke validate`, `yoke-simulator.md`, `yoke-architect.md`, `yoke-boss.md`, `backlog-resync.sh`, `flow-stats.sh`

---

## 7. Stale SKILL.md References to Old `yoke/epics/` Layout

These SKILL.md files reference the deleted `yoke/epics/` directory:
- **sync/SKILL.md** — most outdated; references `worktree-plan.md`, `status/`, `verify-overlap.sh`, `create-worktrees.sh`
- **advance/SKILL.md** — fallback scans `yoke/epics/` for directories
- **groom/advance/SKILL.md** — checks `yoke/epics/{slug}/plan.md`
- **tracks/SKILL.md** — references `yoke/epics/${epic_val}/tasks/*.md`
- **init/SKILL.md** — references `yoke/epics/*/status/*.json` in gitignore

---

## 8. Summary Scorecard

| Area | DB Migration | Read-Only Artifact | Violations |
|------|-------------|-------------------|------------|
| Items (metadata) | ✅ Complete | backlog/*.md generated | None |
| Items (body) | ✅ In DB | backlog/*.md generated | **8 SKILL.md files write to .md directly** |
| BOARD.md | ✅ Generated from DB | Read-only | None |
| tracks.md | ✅ Generated from DB | Read-only | None |
| Epic tasks | ✅ Complete | No disk artifacts | Dual-write bridge in update-status.sh (harmless, no JSON files exist) |
| Epic simulations | ✅ Complete | No disk artifacts | None |
| Epic reviews | ✅ Complete (epics) | No disk artifacts | **Non-epic reviews still file-only** |
| Groom state | ✅ Complete | groom-state.md is dead | **Dead file should be deleted** |
| Ouroboros entries | ✅ Complete | log.md deprecated | **3 SKILL.md files still reference log.md** |
| Wrapup reports | ✅ Complete | wrapups/*.md generated | None |
| Release notes | ✅ Complete | releases/*.md generated | **done-transition.sh dual-writes** |
| Patterns | ❌ Disk-only | N/A — primary artifact | **No DB backup, single point of failure** |
| Designs | ❌ Disk-only | N/A — authored artifact | **Needs DB table** — user decision to migrate |
| Health reports | ❌ Disk-only | N/A — point-in-time snapshots | Acceptable |
| Read paths | Mixed | — | **10 SKILL.md/agents/scripts read .md instead of DB** |

---

## 9. Recommended Actions (prioritized)

### Must-do (YOK-317 blockers — fix BEFORE removing auto-ingest hook)
1. Update 8 SKILL.md files to use `yoke-db.sh items update {N} body --body-file` instead of editing .md directly
2. Update 3 SKILL.md files referencing `ouroboros/log.md` to use `yoke-db.sh ouroboros insert-entry`
3. Delete `yoke/groom-state.md` (already flagged by doctor HC-38)

### Should-do (correctness)
4. Migrate 10 .md-reading SKILL.md files/agents to query DB via `yoke-db.sh items get {N} body`
5. Remove release notes dual-write from `done-transition.sh`
6. Update 5 SKILL.md files with stale `yoke/epics/` references

### Should-do (new DB tables)
7. Create `designs` table — migrate content from `yoke/designs/*.md`, make .md a generated view
8. Create `reviews` table (generalize `epic_reviews`) for standalone issue QA — `yoke-tester.md` currently writes to `yoke/backlog/reviews/YOK-{N}.md` with no DB backing
9. Add `ouroboros_patterns` DB table so patterns.md has a backup

### Consider
10. Remove dual-write bridge from `update-status.sh` (JSON path is dead)
11. Clean up legacy files: `ouroboros/log.md`, `ouroboros/archive/*.md`
