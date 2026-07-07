## Progress: Task #006 -- Update 1 of 2
**Timestamp:** 2026-03-01T12:00:00Z
**Commit:** ba5fed5f
**Summary:** Migrated on-agent-stop.sh and on-bash-complete.sh from filesystem glob dispatch chain discovery to DB queries. Both scripts now query epic_dispatch_chains table via sqlite3, read task status via yoke-db.sh epic task-get, and call update-status.sh with the DB-native interface. find_project_root() updated in both to validate yoke/yoke.db instead of yoke/epics/.
**Files changed:**
- .claude/skills/yoke/scripts/on-agent-stop.sh
- .claude/skills/yoke/scripts/on-bash-complete.sh
