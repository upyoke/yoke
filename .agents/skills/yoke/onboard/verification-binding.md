# Onboard Step 5: Verification Command

Row: `verification-command-binding`.

Declare an Actions test workflow (never deploy/release) as `ci_workflow_file`
first, then bind `quick`, and `full` only when broader. Deployed scopes take
one target: `--environment` or `--requires-base-url`; `quick`/`full` take neither.

No `ci_workflow_file`: the suite runs on this host, and registration cannot
verify bare interpreters (`python3`, `uv`). Run `{quick_argv}` once in the
checkout before `set`. A missing runner (`No module named pytest`) means bind a
self-provisioning argv (`uv run --with pytest python -m pytest -q`) and rerun,
or tell the person what to install. No tests collected passes for an empty suite.

```text
yoke qa registered-command set --project {project} --scope quick --command "{quick_argv}"
```

Write the row evidence with `argv verification` and, beside it, the probe
result (`probe: passed|no tests|runner missing: <recovery>|skipped: CI`).

Read (`{scope}`: quick/full/e2e/smoke):

```text
yoke qa plan get registered-command-{scope} --project {project} --full
```

Missing plan: confirm, then `set`.

Review-only: no default command; never manufacture a green or a permanently
failing blocking gate. No suite: `yoke qa no-tests attest`, then write the row `configured`.
