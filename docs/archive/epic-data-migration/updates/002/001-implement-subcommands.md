## Progress: Task #002 -- Update 1 of 1
**Timestamp:** 2026-03-02T02:52:00Z
**Commit:** 42a3cf88
**Summary:** Implemented all 15 new subcommands in yoke-db.sh epic and fixed cmd_task_upsert to use ON CONFLICT instead of INSERT OR REPLACE. All acceptance criteria verified: task body CRUD, history-insert, dispatch-chain CRUD, review-insert/get, progress-note CRUD with sync tracking, simulation upsert/get. Existing 39-test suite passes with zero failures.
**Files changed:**
- `.claude/skills/yoke/scripts/yoke-db.sh epic` (modified -- 665 insertions, 11 deletions)
