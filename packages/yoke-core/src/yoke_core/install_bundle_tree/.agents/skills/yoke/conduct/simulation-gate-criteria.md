# Conduct — Simulator dispatch and receipt

Spawn `yoke-simulator` ([role spawn](../shared/role-spawn.md)). The reply starts
`SIMULATION: CLEAN` or `SIMULATION: GAPS FOUND`, then `EPIC: PREFIX-N`. Empty _epic_ref halts first.
Compressed two-phase mode unless sim_force_standard_integration is true.
Code authority is each task's registered worktree or diff, not main.
Composed migrations: add the ledger and rehearsal evidence from
`yoke packets render --role simulator_agent --topic core --detail full`.

```text
yoke workflow-item epic-task simulation-upsert --epic PREFIX-N --phase integration --stdin --json < {REPORT_FILE}
```

Write once; require verified=true and use the returned verdict. Uncertain
write: read back, never rewrite:

```text
yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase integration --json
```
