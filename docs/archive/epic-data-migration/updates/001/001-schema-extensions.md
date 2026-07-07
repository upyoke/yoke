## Progress: Task #001 -- Update 1 of 1
**Timestamp:** 2026-03-01T12:00:00Z
**Commit:** b82a23e8
**Summary:** Implemented all schema extensions for epic lifecycle data. Added `_add_column_if_not_exists()` helper to `sprint-db.sh` for idempotent ALTER TABLE ADD COLUMN. Extended `cmd_init()` with 5 new tables (epic_task_history, epic_dispatch_chains, epic_reviews, epic_progress_notes, epic_simulations) and 8 new columns on epic_tasks. All acceptance criteria verified: tables have correct columns, constraints, indexes, and defaults; init is idempotent (runs 3x without error); existing data preserved after migration. Comprehensive test suite (135 assertions) created. All existing tests (sprint-db: 51, epic-db: 39) continue to pass.
**Files changed:**
- `.claude/skills/yoke/scripts/sprint-db.sh` (modified -- added helper + schema extensions)
- `.claude/skills/yoke/scripts/tests/test-schema-extensions.sh` (new -- 135 assertions across 11 test cases)
