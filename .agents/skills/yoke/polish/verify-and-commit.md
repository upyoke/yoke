# Polish — verify and commit

The review stage is the unique pinned forward edge from an implementing-bucket
stage to a reviewing-bucket stage at or before the polish entry; stop if not
unique. Rerun every case not passing on the current commit; prove each changed
lane through its own task requirements.

```text
yoke qa plan materialize --item PREFIX-N --transition <review-stage>
yoke qa case run --requirement-id <id>
```

Prompt or large-script changes also run `yoke watch doctor -- --quick`.
Save the capture with
`yoke items structured-field replace PREFIX-N --field test_results --stdin`.
Commit specific files per lane; no commit after the final passing run.
