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

The same short-lived provider boundary lets the registry stack own its
non-secret infrastructure and delivery role-routing variables. Local applies
receive Variables write; hosted refresh/preview receives Variables read. The
role values flow directly from Pulumi role outputs, so copying ARNs through the
GitHub settings UI is bootstrap drift rather than an operating procedure.

The stable `runnerFleetGithubWebhook` waits for both Lambda Function URL
invocation grants. `runnerFleetRoutingVariable` then waits for that complete
ingress barrier before routing work to the fleet.

## First Apply And Existing Variables

Check live state before the first apply:

```bash
yoke github-actions runners status --project <project>
```

All imports and applies below are operator-attended local operations using the
project's `aws-admin` capability. GitHub Actions receives a read-only provider
token and runs preview only.

If the action is `adopt_runner_routing_variable`, the configured variable name
already exists. Do not apply or overwrite it directly. The variable resource
is parented by the runner-fleet component and uses its explicit GitHub
provider, so both identities must already exist in stack state. For a new
stack, keep `routing_enabled=false`, render and apply the base stack once, and
confirm a zero-change preview. That creates the component, provider, webhook,
and fleet without managing the existing variable. Then set
`routing_enabled=true`, rerender, and from the rendered `infra/` directory have
Pulumi generate an import record with the exact parent and provider:

```bash
yoke runner-fleet exec --project <project> \
  --settings-file <stack-config.json> -- \
  pulumi preview --stack <runner-fleet-stack> --refresh \
  --import-file <preview-import-file.json> --non-interactive

yoke runner-fleet exec --project <project> \
  --settings-file <stack-config.json> -- \
  pulumi import --stack <runner-fleet-stack> \
  --file <runner-variable-import-file.json> \
  --protect=false --generate-code=false --yes --non-interactive
```

After the base stack is converged, the preview import file must contain exactly
one create: type `github:index/actionsVariable:ActionsVariable`, name
`runnerFleetRoutingVariable`. Copy only that complete record to
`<runner-variable-import-file.json>`, preserve its generated `parent` and
`provider` fields unchanged, and set its `id` to
`<repository-name>:<variable-name>`. Stop if the candidate is missing, is not
unique, lacks either relationship, or the preview contains a replacement or
delete. A positional import without `--parent` and `--provider` creates the
wrong Pulumi identity for this child resource.

Preview after import and verify the only planned change is the compact
`runner_labels` value, then apply and require a final zero-change refresh
preview. An unadopted collision fails loudly rather than being treated as
managed state.

`routing_enabled` defaults to `false`. With routing disabled, absence of the
variable is the only clean hosted-fallback state. If status returns
`resolve_runner_routing_variable`, review ownership and deliberately delete or
rename the nonmatching variable, or follow the base-apply and adoption sequence
above before any apply that declares the variable.
Arm and disarm only through the capability plus runner-fleet apply; direct
variable writes are drift. V1 runs one ephemeral host with DNS and web egress.
Deployment workflows must explicitly list every environment they reach over
SSH in `network.deployment_ssh_environments`. The renderer resolves each
selected active environment to its Pulumi stack, and the runner stack consumes
that stack's established `originElasticIpAddress` output as one exact `/32`
TCP/22 egress rule. Standalone VPS stacks that have no environment row belong
in `network.deployment_ssh_stack_names`; entries must be Pulumi stack names or
qualified `org/project/stack` references, and bind to the standalone stack's
established `vpsElasticIpAddress` output. The renderer carries this provenance
as an exact stack-to-output contract, appends standalone stacks after
environment-derived stacks, and removes overlap without widening the rule.
Both lists default empty. Literal addresses and CIDRs are not configuration:
every target and exact output are resolved through a `Pulumi.StackReference`,
and missing outputs or unrestricted SSH egress are never inferred.

See the [Pulumi ActionsVariable import contract](https://www.pulumi.com/registry/packages/github/api-docs/actionsvariable/#import).
