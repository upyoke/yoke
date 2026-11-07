---
name: wrapup
description: "Structured session wrap-up: feedback, unfinished business, session summary."
argument-hint: "(no arguments)"
---

# /yoke wrapup

Keep trivial sessions brief.

```text
yoke items overview list --json
yoke events anomalies --since "4 hours ago"
```

1. Show uncommitted paths; ask whether to commit, stash or continue.
2. List items with active worktrees by `public_ref`; warn about open lanes.
3. Report: what we did, what went wrong, what took too long, what worked,
   unfinished business.
4. File one feedback note per observation; use failed, new, unclear,
   observation or idea:

   ```text
   yoke feedback --to universe --category "{category}" --evidence "{project observation}"
   yoke feedback --to yoke --category failed --evidence "{Yoke problem}"
   ```

5. Ask before filing each follow-up through `/yoke idea`.
6. Checkpoint each unfinished item you hold; live release-wait claims stay
   with their owning skill:

   ```text
   yoke items progress-log append PREFIX-N --headline "Session checkpoint" --content "{objective, blockers, next action, evidence}" --source wrapup
   ```

7. Summarize and commit authored artifacts.
