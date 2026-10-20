# Usher — record the parent

Only after every lane landed, set the parent's `merged_at`, then walk
forward one stage at a time to the delivery wait:

```text
yoke lifecycle transition PREFIX-N --from LIVE_STAGE --to NEXT_STAGE --reason "Generated-task lanes landed"
```
Next: [deploy](deploy.md).
