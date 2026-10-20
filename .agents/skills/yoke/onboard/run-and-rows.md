# Onboard — Run And Rows

Resume this project's run; init only when none exists. Follow `run.next_action`.

```text
yoke onboard checklist get --project {project} --json
yoke onboard checklist init --project {project} --checkout {checkout} --json
```

Each step writes its rows (`--row-status row=status --evidence`). Only two
stops: profile confirmation and the infra `[y/N]`. On failure write `blocked`
with recovery and stop; never undo prior steps.
