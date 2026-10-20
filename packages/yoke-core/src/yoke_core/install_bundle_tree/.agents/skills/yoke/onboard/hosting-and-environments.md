# Onboard Steps 4–5: Hosting And Delivery

No cloud writes before the step-7 yes. Rows: `hosting-setup`, `capability-setup`;
step 5 `environment-registration`, `project-structure-setup`, `delivery-setup`.
Old CI, scripts and `.yoke/deployment-flows.json` are hints: never edit or depend on them.

## Step 4: Hosting

Read `hosting_posture`; if empty, ask once and write it. For AWS, import only
missing keys through stdin, after explicit approval. Not `ready`: write
`hosting-setup=blocked` and stop; never re-request a saved pair or use ambient
credentials. Never store a GitHub token.

```text
yoke aws admin-status --project {project} --json
```

## Step 5: Delivery

Pick exactly one branch; a failed managed step never falls back to no-host.

- **Managed:** register site and environments (never overwrite an existing one), validate the flow
  (`execution_supported=false` creates it disabled, no default), create it.
- **Merge-only:** a flow with two `auto` stages, `merged` and `complete`,
  and no tier or environment; its `target_tier` read must print nothing.
- **No default:** remove the project `deploy_defaults`; the read must print nothing.

Set the default for dash, issue, epic and blitz; never `--apply-to-all`.
Disable a referenced flow rather than edit it.

```text
yoke workflows delivery-default set --project {project} --workflow {workflow} --flow {flow_id}
```

Then [verification-binding.md](verification-binding.md), [governed-database.md](governed-database.md);
add one `test_roots` entry per test tree. Next: [domain-and-deploy.md](domain-and-deploy.md).
