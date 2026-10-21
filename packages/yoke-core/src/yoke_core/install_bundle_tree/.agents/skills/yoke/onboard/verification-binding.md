# Onboard Step 5: Verification Command

Row: `verification-command-binding`.

Declare an Actions test workflow (never deploy/release) as `ci_workflow_file`
first, then bind `quick`, and `full` only when broader. Deployed scopes take
one target: `--environment` or `--requires-base-url`; `quick`/`full` take neither.

```text
yoke qa registered-command set --project {project} --scope quick --command "{quick_argv}"
```

Read (`{scope}`: quick/full/e2e/smoke):

```text
yoke qa plan get registered-command-{scope} --project {project} --full
```

Missing plan: confirm, then `set`.

Review-only: no default command; never manufacture a green or a permanently
failing blocking gate. No suite: `yoke qa no-tests attest`, then write the row `configured`.
