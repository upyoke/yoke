# Onboard — Run And Rows

Resume this project's run; init only when none exists. Follow `run.next_action`.

```text
yoke onboard checklist get --project {project} --json
yoke onboard checklist init --project {project} --checkout {checkout} --json
```

Each step writes its rows. Only two stops: profile confirmation and the infra
`[y/N]`. On failure write `blocked` with error and recovery, then stop; never
undo prior steps.

```text
yoke onboard checklist --run-id {run_id} --row-status {row}=configured --evidence {row}="{what was written and where}"
yoke onboard checklist --run-id {run_id} --row-status {row}=blocked --blocker {row}="{failure}; {recovery}"
```
