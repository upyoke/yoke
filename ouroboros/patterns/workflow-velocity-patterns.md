# Workflow & Velocity Patterns

Cross-link back from the [pattern catalog](../patterns.md) for the full Ouroboros index.

## P-20: SKILL.md-only tasks are the fastest item type

**First observed:** 2026-03-01 (T3, T4 conductors)
**Promoted:** 2026-03-01
**Occurrences:** 5+ entries across T3, T4, T5 conductor sessions
**Status:** Active — ongoing planning heuristic

Pure prompt engineering changes (adding conventions/constraints to agent definitions, new SKILL.md commands) average 2-5 minutes per item. No tests needed, no code to break, no dependencies. These should always be classified as XS/S in sprint sizing.

**Timing reference:**
- SKILL.md-only: 2-5 min average
- Shell script refactors: 5-7 min average
- Large structural extractions: 10-15 min average
- Combined scope (tests + docs): 15-73 min (high variance)

---

## P-21: Conductor pattern (orchestrating full track execution) is effective

**First observed:** 2026-02-27 (GEULAH/T1 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 10+ conductor sessions across SINAI and MERAGLIM sprints
**Status:** Active — confirmed effective pattern

Sequential dispatch through active -> done (Engineer + Test each), then merge all in sequence. Each merge builds on the previous merged state of main, so conflicts are always current-branch vs fully-resolved main. More predictable than interleaving merges with implementation.

**Metrics (SINAI sprint):**
- T1: 7 items, all merged, 7 PRs
- T2: 6 items, all merged, 6 PRs (~10 min merge overhead on YOK-232)
- T3: 3 items, all merged, 3 PRs (fastest track)
- T4: 3 items, all merged, 3 PRs
- T5: 6 items, all merged, 5 PRs

**Action:** Pattern codified. Key bottlenecks are Tester reliability and merge friction, not engineering.

---

## P-22: Accelerated flow is efficient for small-to-medium issues

**First observed:** 2026-03-01 (all conductor tracks)
**Promoted:** 2026-03-01
**Occurrences:** 15+ entries across all tracks
**Status:** Active — core workflow pattern

advance -> implement -> test -> merge -> done in continuous flow. Average cycle time per item: ~5-15 minutes for small-to-medium issues. The biggest overhead is the merge pipeline (~2-3 minutes per item: push, PR create, CI wait, PR merge, local sync).

**Action:** Accelerated flow rules codified in `.claude/rules/accelerated-flow.md`. Conductor tracks confirm this is the optimal flow for issues that don't need formal pipeline.

---

## P-23: Sequential worktree strategy works cleanly for track execution

**First observed:** 2026-03-01 (T2, T5 conductors)
**Promoted:** 2026-03-01
**Occurrences:** 4+ entries
**Status:** Active — confirmed effective pattern

Create all worktrees upfront, engineer in each, then merge in sequence. No merge conflicts between related items despite touching the same subsystems, because each merge builds on the previous.

**Action:** Conductor flow uses this by default. Note: worktree limit (max_active_worktrees config) can block this for large tracks — scale limit based on active track count.

---

## P-24: Simulation-fix-resimulate cycle converges in 1-2 rounds

**First observed:** 2026-02-26 (YOK-167 groom-conductor)
**Promoted:** 2026-03-01
**Occurrences:** 4+ entries across simulator agents
**Status:** Active — confirmed effective pattern

Plan-phase simulation catches real gaps; Architect fixes in one iteration; re-simulation confirms clean. The cycle works well. First simulation found 5 gaps, Architect fixed all, re-simulation confirmed CLEAN with 25 paths traced.

**Action:** Integration simulation should include a trial-merge step (git merge --no-commit --no-ff main in temp clone) to also catch post-merge integration issues (see P-12).
