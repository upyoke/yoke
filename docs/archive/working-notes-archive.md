# Working Notes Archive

> Archived from `yoke/BOARD.md` on 2026-02-24 as part of YOK-106 Task 004.
> Working Notes are no longer maintained in BOARD.md. Per-item context now lives
> in backlog item bodies (`yoke/backlog/{NNN}.md`).

---

## Working Notes

**Where to put implementation plans:** For items that bypass the PRD → epic pipeline (standalone issues dispatched via `YOK-N`), put all details, implementation plan, and log in the backlog item itself (`backlog/{NNN}.md`). BOARD.md is just the board + reference — not a place for per-item detail.

### YOK-6 Complete

**Result:** Merged via PR #74. Epic #42 closed.
- `merge-settings.sh` replaces LLM-driven settings.json merge in init step 4
- `check-prerequisites.sh` upgraded from file-exists to content validation (grep -Fq)
- Script counts updated 11→14 across all docs
- Integration simulation: 17 paths traced, 0 gaps

**Bugs found during YOK-6 sessions — all fixed:**
- YOK-38: Added `--add-label "type:epic"` to reuse branch in sync-to-github.sh
- YOK-39: Fixed worktree_path from `REPO_PARENT/worktree-{slug}` to `REPO_ROOT/.worktrees/{slug}`
- YOK-40: Added label management to `cmd_post_comment` in backlog-registry.sh

### Bug batch: YOK-43, YOK-41, YOK-38, YOK-39, YOK-40

All five fixed in one session. See individual backlog items for details.

### YOK-42 Ouroboros — Complete (9/9 tasks)

**Session 1 (2026-02-23):** Plan simulation → dispatch tasks 001-003.

**Plan simulation:** Found 6 gaps (0 critical, 2 warning, 4 note). Fixed GAP #1 (OVERVIEW.md stale counts in task 009), GAP #3 (task 004 now depends on 003 — both modify simulate/SKILL.md), GAP #4 (HC-5 now checks OVERVIEW.md). Re-simulation: clean.

**Bug found:** YOK-50 — `update-status.sh` used `$JSON_HELPER` before defining it (line 31 vs 51). Fixed by moving definition earlier. Tracked and closed.

**Tasks completed (session 1):**
- 001 (XS): Ouroboros directory structure — `.claude/ouroboros/{log.md, patterns.md, archive/.gitkeep}` — pass on first attempt
- 002 (S): Reflection sections in all 6 agent definitions — Engineer gets Bash heredoc, 5 read-only get REFLECTION-START/END delimiters — pass on first attempt
- 003 (M): Reflection capture in 5 SKILL.md commands — prd-new, design, plan, simulate, dispatch — pass on first attempt

**Session 2 (2026-02-23):** Dispatch tasks 004-009, accelerated flow (parent session implementing directly).

**Tasks completed (session 2):**
- 004 (M): System-wide simulation — `--system` flag on simulate SKILL.md, 5 gap categories in Simulator agent
- 005 (L): doctor.sh — 12 health checks, branded "Ouroboros Health Report", tested against live repo (7 pass, 4 warn, 1 fail from expected worktree context)
- 006 (S): /yoke doctor SKILL.md — invokes doctor.sh, --fix for auto-repair of trivial issues
- 007 (M): /yoke curate SKILL.md — prompt-driven log curation, clustering, ticketing, archiving, pattern promotion
- 008 (S): /yoke standup bare invocation — cross-project aggregate standup with Ouroboros curator-filed tickets section
- 009 (S): Documentation sweep — all 6 docs updated (root SKILL.md, CLAUDE.md, commands.md, agents.md, scripts.md, OVERVIEW.md), counts verified from disk (16 scripts, 29 commands), Ouroboros branded throughout

**Next:** Integration simulation + merge via `/yoke merge ouroboros`.

### YOK-96 Safe Worktree Lifecycle — Pipeline Complete

**Full pipeline run:** PRD → backlog item (YOK-96) → plan (5 tasks) → plan simulation → sync (GH #197-#202) → integration simulation.

**Plan simulation:** 20 paths traced, 7 gaps (0 critical, 4 warning, 3 note). Fixes applied:
- GAP #1: HC-18 grep pattern (glob→substring)
- GAP #2: Done-transition BOARD.md commit gap (added AC-11 to Task 003)
- GAP #4: Epic branch stash naming (generic `_identifier` in Task 002)
- GAP #5: Stale doc counts (explicit before/after values in Task 005)

**Integration simulation:** 26 paths traced, 7 gaps (0 critical, 5 warning, 2 note). Fixes applied:
- GAP #1: Task 003 stash drop — `_yok_id` → `_identifier` (consumer consistency with Task 002)
- GAP #2: HC-18 grep — `yoke-pre-rebase-YOK-` → `yoke-pre-rebase-` (match both branch types)
- GAP #3: scripts.md HC list — add HC-16, HC-17, HC-18 (not just HC-18)
- GAP #4: Root SKILL.md added to Task 005 file manifest (13→18 checks)
- GAP #5: README.md added to Task 005 file manifest (12→18 checks)

**Key insight:** Plan-sim fixes to Task 002's interface (generic stash identifier) were NOT auto-propagated to consumers (Tasks 003, 005). Integration sim caught this. Fix-application process needs forward-trace through dependency chain.

**Status:** Ready for dispatch. All 5 tasks pending on worktree `feature/safe-worktree-lifecycle`.
