# Conduct — preview target

```text
yoke projects capability-settings get --project {PROJECT} --cap-type ephemeral-env --json
yoke ephemeral-env create {PROJECT} {BRANCH} --item PREFIX-N --json
yoke deployment-runs start-for-item PREFIX-N --project {PROJECT} --flow {FLOW_ID} --environment ephemeral --json
yoke qa case run --requirement-id {requirement_id} --base-url {URL} --expected-branch {BRANCH} --expected-sha {HEAD_SHA}
```

No capability: warn and skip. Create once per branch and dispatch. Trigger
`flow` uses start-for-item; `github-push` uses `yoke github-actions find-run`
and `yoke github-actions wait-run`. Failure sets URL=none; halt only if a blocking Browser case
needs it. After the Tester returns: `yoke ephemeral-env update {env_id} status stopped`.
