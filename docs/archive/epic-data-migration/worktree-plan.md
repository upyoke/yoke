## Worktree: feature/epic-db-migration
Branch: feature/epic-db-migration
Tasks: #001, #002, #003, #004, #005, #006
Files touched:
  - .claude/skills/yoke/scripts/sprint-db.sh (modify) — #001
  - .claude/skills/yoke/scripts/yoke-db.sh epic (modify) — #002
  - .claude/skills/yoke/scripts/yoke-db.sh (modify) — #003
  - .claude/skills/yoke/scripts/tests/test-yoke-db.sh epic (modify) — #004
  - .claude/skills/yoke/scripts/update-status.sh (modify) — #005
  - .claude/skills/yoke/scripts/on-agent-stop.sh (modify) — #006
  - .claude/skills/yoke/scripts/on-bash-complete.sh (modify) — #006
Generated files (auto-resolve on merge):
  - yoke/BOARD.md
  - yoke/backlog/*.md

## Dependency groups
- epic-db-core: sprint-db.sh, yoke-db.sh epic, yoke-db.sh (tasks #001 → #002 → #003)
- hook-scripts: on-agent-stop.sh, on-bash-complete.sh (task #006)

## Same-file modifications
- No same-file conflicts across tasks. Each file is modified by exactly one task.

## File overlap check: PASS

## Execution order:
- All tasks are in a single worktree, sequenced via dependencies.
- Phase 1 (Schema): 001
- Phase 2 (CRUD + Tests): 002 → 003, 004 (parallel after 002)
- Phase 3 (Write Path): 005 (after 001), 006 (after 002)
