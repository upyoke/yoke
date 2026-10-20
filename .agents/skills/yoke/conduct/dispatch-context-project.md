# Conduct — project context and QA roster

```text
yoke project-structure get --project {PROJECT} --family context_routing --json
yoke qa requirement list --item PREFIX-N --json
```

Follow [the shared project-context recipe](../implement/implementing/project-context.md)
in the claimed lane. Pass each requirement's id, case_key, method and
expected outcome; never invent test commands. Runnable cases:

```text
yoke qa case run --requirement-id {requirement_id}
```
