# Conduct — project context and QA roster

Lists: `next_offset` → `--offset`; keep filters.

```text
yoke project-structure get --project {PROJECT} --family context_routing --json
yoke qa requirement list --item PREFIX-N --json
```

Follow [project context](../implement/implementing/project-context.md)
in the lane. Pass each requirement's id, case_key, method and
expected outcome; never invent test commands. Cases:

```text
yoke qa case run --requirement-id {requirement_id}
```
