## Progress: Task #005 -- Update 1 of 2
**Timestamp:** 2026-03-02T04:00:00Z
**Commit:** 7102224b
**Summary:** Rewrote update-status.sh to support dual interface (DB-native + legacy path-based). Added path-detection heuristic, DB writes via yoke-db.sh epic, rewritten auto_unblock() querying epic_tasks, and updated update_epic_checkbox() to read from DB. All 38 existing legacy-interface tests pass.
**Files changed:**
- `.claude/skills/yoke/scripts/update-status.sh`
