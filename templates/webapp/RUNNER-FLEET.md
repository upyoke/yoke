# GitHub Actions Runner Fleet

The optional runner fleet is privileged and fail-safe. Its capability must
explicitly select the canonical `github` binding and an exact
`github_app_environment`; no product-binding, primary, prod, or stage fallback
is inferred. The environment must carry `settings.github_app` on the binding's
API origin. The installation needs `administration: write`,
`repository_hooks: write`, and `actions_variables: write`; Variables write is
also required while disabling routing so Pulumi can delete its variable.

Yoke validates the complete runner-stack intent from its renderer snapshot and
passes Pulumi a digested envelope. Before constructing any resource, Pulumi
checks the exact stack name, AWS capability/region, App and repository identity,
routing variable and labels, enabled state, instance sizing, runner limits, and
lifecycle settings. Its repository-scoped token exists only as the process aliases
`RUNNER_FLEET_GITHUB_TOKEN` and `GITHUB_TOKEN`; it is not a resource input,
output, state value, host file, or Lambda setting.

The stable `runnerFleetGithubWebhook` waits for both Lambda Function URL
invocation grants. `runnerFleetRoutingVariable` then waits for that complete
ingress barrier before routing work to the fleet.

## First Apply And Existing Variables

Check live state before the first apply:

```bash
yoke github-actions runners status --project <project>
```

If the action is `adopt_runner_routing_variable`, the configured variable name
already exists. Do not apply or overwrite it directly. From the rendered
`infra/` directory, adopt it with the same validated runner authority:

```bash
yoke runner-fleet exec --project <project> \
  --settings-file <stack-config.json> -- \
  pulumi import --stack <runner-fleet-stack> \
  github:index/actionsVariable:ActionsVariable \
  runnerFleetRoutingVariable <repository-name>:<variable-name>
```

The Pulumi GitHub provider's import id is `repository-name:variable-name`.
Preview after import and review the planned compact `runner_labels` value. An
unadopted collision fails loudly rather than being treated as managed state.

`routing_enabled` defaults to `false`. With routing disabled, absence of the
variable is the only clean hosted-fallback state. If status returns
`resolve_runner_routing_variable`, review ownership and deliberately delete or
rename the nonmatching variable, or enable routing and import it before apply.
Arm and disarm only through the capability plus runner-fleet apply; direct
variable writes are drift. V1 runs one ephemeral host with DNS and HTTPS egress.

See the [Pulumi ActionsVariable import contract](https://www.pulumi.com/registry/packages/github/api-docs/actionsvariable/#import).
