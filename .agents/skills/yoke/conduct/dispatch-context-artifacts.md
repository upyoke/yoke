# Conduct — reflections and review

Without the Agent reflection hook (Codex), capture each return:

```text
yoke ouroboros reflection capture --default-agent {ROLE} --project {PROJECT} --text-file {RESPONSE_FILE}
yoke workflow-item epic-task review-insert --epic PREFIX-N --task-num {task_num} --verdict PASS --head-sha {REVIEWED_HEAD_SHA} --body-file {REVIEW_FILE}
```

Insert the actual verdict with the full commit the Tester reviewed. Task
reviews never credit parent QA cases.
