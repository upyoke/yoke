---
name: approve
description: "Record your decision on a deployment run paused at a Yoke human-approval stage."
argument-hint: "RUN-ID [--note \"...\"]"
---

# /yoke approve RUN-ID [--note "..."]

```text
yoke deployment-runs approve RUN-ID --json
```

Pass the user's `--note` when given. If `stage_approved` is false, report the outstanding approvers and stop; if true, resume the run from `current_stage`. Create no other run, item update or approval record.
