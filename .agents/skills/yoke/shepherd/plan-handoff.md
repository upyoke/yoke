# Shepherd — Architect and Simulation

```bash
yoke readiness prd-validate PREFIX-N
```
FAIL: BLOCKED. Write the architect's `technical_plan`,
`worktree_plan`, then tasks (`yoke workflow-item epic-task add`); each task's
`## Files Touched` is its only file list. Under `required_per_task`, claim
each task's paths; a non-pass gate is NOT_READY:
```bash
yoke claims path register --item ITEM --task-num {task_num} --paths PATHS --allow-planned
yoke claims path register --item ITEM --task-num {task_num} --mode exception --exception-reason "Task declares no repository files"
yoke claims path required-gate ITEM --json
```
Simulate and persist every report; on gaps dispatch the architect with
`Fix mode.` and the report, at most MAX_SIMULATOR_FIX_CYCLES, then halt (no
self-waiver). A NOT_READY replan removes only planning tasks:
```bash
yoke workflow-item epic-task simulation-upsert --epic ITEM --phase plan --stdin
yoke workflow-item epic-task remove --epic ITEM --task-num {task_num} --reason "Replan after NOT_READY"
```
