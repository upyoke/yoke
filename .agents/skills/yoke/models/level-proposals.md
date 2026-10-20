# Model Level Proposals

Author add/move/retire/change entries from researched facts; thresholds rise
strictly within each model. Present the complete proposal; apply only after
operator approval, using its `apply_command`.

```text
yoke models level-proposal --levels-only --stdin < changes.json > /tmp/levels.json
```

When `equals_shipped_defaults` is true, run `yoke settings unset levels`.
Otherwise say a stored document stops following shipped defaults.
