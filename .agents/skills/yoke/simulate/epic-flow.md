# Simulate — epic flow

```text
yoke epic-tasks list --epic {epic-ref} --json
yoke workflow-item epic-task body-get --epic {epic-ref} --task-num {task_num}
yoke workflow-item epic-task simulation-upsert --epic {epic-ref} --phase {phase} --stdin --json < {REPORT_FILE}
```

All tasks planned: plan phase. All completed: integration (compressed unless
`sim_force_standard_integration`). Mixed: wait. Task lanes hold the code.
Persist every report; claim CLEAN only from a `verified=true` receipt.
