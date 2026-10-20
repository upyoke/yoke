# Onboard Step 5: Verification Command

Declare an Actions test workflow (never deploy/release) as `ci_workflow_file`
first, then bind `quick`, and `full` only when broader. Deployed scopes take
one target: `--environment` or `--requires-base-url`.

```text
yoke qa registered-command set --project {project} --scope quick --command "{quick_argv}"
```

Review-only: no default command. No suite: `yoke qa no-tests attest`.
