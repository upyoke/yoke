# Merge & Integration Patterns

Cross-link back from the [pattern catalog](../patterns.md) for the full Ouroboros index.

## P-11: Merge-worktree.sh rebase fails with cascading conflicts on parallel branches

**First observed:** 2026-02-28 (YOK-196 T2 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 7+ entries across conductor sessions
**Status:** Partially addressed (auto-resolve for generated files done; rebase-to-merge fallback not yet implemented)

`merge-worktree.sh` uses `git rebase` which hits O(N) conflicts on long-lived parallel branches. With 31 commits and overlapping files, resolving one-by-one was impractical. YOK-196 had to bypass merge-worktree.sh entirely.

**Root cause:** Companion epics developing in parallel create conflict density that rebase can't handle efficiently. A merge-based strategy handles this in O(1).

**Action:** Multiple merge-hardening items done (YOK-185, 198, 199, 206, 207, 208, 209, 235). Recommendation: detect high conflict density during rebase (>2 conflicts) and fall back to merge-commit strategy.

---

## P-12: Cross-epic parallel development creates invisible naming mismatches

**First observed:** 2026-02-28 (YOK-196 T2 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 1 critical instance (YOK-195/YOK-196 `_query_item` vs `query_item`)
**Status:** Active — no automated prevention mechanism

YOK-196 used `_query_item()` as inline fallback; YOK-195's `item-db.sh` exports `query_item()`. Works in isolation, breaks on integration. Only post-merge simulation or trial-merge testing can catch it.

**Action:** Integration simulation (found GAP #1, severity CRITICAL) was the catch. Recommendation: mandate naming contracts when epics share dependencies; make integration simulation mandatory before merge.

---

## P-13: Dirty repo root from parallel sessions blocks merge

**First observed:** 2026-03-01 (T2 conductor YOK-232 merge)
**Promoted:** 2026-03-01
**Occurrences:** 6+ entries across T2, T4 conductor sessions
**Status:** Partially addressed (YOK-235 expanded YOKE_SHARED_FILES; per-track pre-merge sweep not yet implemented)

Parallel track sessions modify files on main (release notes, doctor.sh, backlog items, wrapups) without committing. merge-worktree.sh exit 4 blocks on these "user-authored files at risk."

**Action:** YOK-235 expanded YOKE_SHARED_FILES. Recommendation: before starting merge phase, run a single sweep to commit all dirty files on main.

---

## P-14: Generated files not in auto-resolve list cause avoidable merge conflicts

**First observed:** 2026-03-01 (T4 conductor, YOK-193)
**Promoted:** 2026-03-01
**Occurrences:** 2+ instances (health reports, BOARD.md before auto-resolve)
**Status:** Active — health reports not yet in auto-resolve list

Generated files (health reports from `doctor.sh --only status-consistency`, BOARD.md before YOK-198) created in worktrees conflict with same files on main.

**Action:** BOARD.md auto-resolve done (YOK-198). Health reports should be added to auto-resolve list or excluded from worktree commits.

---

## P-15: Pre-merge dirty-file sweep eliminates one-by-one discovery friction

**First observed:** 2026-03-01 (T2, T4 conductors)
**Promoted:** 2026-03-01
**Occurrences:** 4+ idea/recommendation entries
**Status:** Not yet implemented

Before starting the merge phase of a track, run a single sweep to commit all dirty files on main. This avoids discovering stray files one-by-one during sequential merges. The 4-retry cycle for YOK-232 (~10 min overhead) would have been eliminated.

**Action:** Recommendation: add pre-merge commit step to conductor flow or done sub-skill step 2b. Should sweep yoke/backlog/*, yoke/BOARD.md, yoke/releases/, and yoke/ouroboros/wrapups/.
