# /yoke strategize — registered strategy state surfaces

## Registered Strategy State Surfaces

Use the registered carry and checkpoint wrappers for strategize state. The
phase files show the capture/JSON details; these are the command surfaces:

```bash
yoke strategy checkpoint latest --project {project}
yoke strategy carry register-new --project {project} --horizon-days {days} --carry-limit {limit}
yoke strategy carry summary --project {project} --horizon-days {days} --carry-limit {limit} --new-ids {item-id}
yoke strategy carry candidate-set --project {project} --horizon-days {days} --carry-limit {limit} --new-ids {item-id}
```

