# GitHub Actions Runner Fleet

The optional runner fleet is privileged and fail-safe. Its capability must
explicitly select a verified repository binding and an exact `github_app`; no
product-binding, primary, prod, or stage fallback is inferred. Use a dedicated
operator-only GitHub App capability when the product App does not carry runner
administration permissions. The capability-owned App must use the binding's
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
stack, keep `routing_enabled=false`, apply the base stack once, and
confirm a zero-change preview. That creates the component, provider, webhook,
and fleet without managing the existing variable. Then set
`routing_enabled=true`; the runner-fleet executor materializes the selected
project's installed Pack source in its private workspace and has Pulumi
generate an import record with the exact parent and provider:

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
variable writes are drift. The fleet runs ephemeral hosts with DNS and web egress.
Each GitHub runner registration still accepts exactly one job. After a job, the
host deletes that runner's work directory and immediately registers a fresh
ephemeral runner. The host remains available until
`lifecycle.idle_shutdown_minutes` elapses without another job, then the
external reaper terminates it and returns the fleet to zero. A failed rearm is
bounded by the bootstrap retry policy and replaces the host rather than
silently converting it into a persistent runner. Each successful rearm starts
that host's idle window again; fleet-wide queue activity cannot leave a
pre-job idle timestamp attached to the new one-job registration.
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

## Canonical lifecycle-state cutover

The project owns live SSM repair. Pulumi deliberately ignores lifecycle
parameter value changes; applying new source does not convert existing state.
Suspend new CI dispatch and adopt the candidate source locally. Set capability
`lifecycle.writers_paused=true` and `lifecycle.code_frozen=true`; the rendered
Pulumi keys are `lifecycle_writers_paused` and `lifecycle_code_frozen`.
Both requested controls are bound by the existing digested authority intent;
false controls leave ordinary authority envelopes unchanged.

Capture the old Lambda code hashes, configuration and Pulumi state. Run the
operator-attended runner-fleet refresh/preview and require only reserved
concurrency changes for the three existing writer functions. Code, handler,
runtime, environment and timeout must retain their exact old state values:
`ignoreChanges` on those custom resources provides the pause-only boundary.
Refuse replacement, producer input drift or an unverified old-code baseline.
Apply the reviewed pause-only plan, verify all three concurrencies are zero
and the code/config hashes are unchanged, then drain for the greatest old
function timeout. Do not rely on the provider ordering code and concurrency
updates to the same function.

After drain and active-host admission, clear `lifecycle.code_frozen` while
keeping `lifecycle.writers_paused=true`. Refresh/preview/apply the strict new
code while all functions remain paused. Verify its exact code hashes and
concurrency before any parameter conversion. The code freeze requires paused
writers and refuses before resources when used with active writers.

Refuse conversion while any fleet ASG host is active. Snapshot exact SSM
parameter bytes and versions plus the prior configuration and concurrency
values. Classify the known epoch-second fields, including nested termination
state and per-host idle clocks, using Decimal directly at microsecond precision.
Convert zero sentinels for missing clocks to null; retain opaque queue tokens,
job identifiers and non-temporal fields byte-for-byte. Validate the complete
snapshot and unchanged parameter versions before the first write. Record each
new SSM version, read back and verify every converted value, and bind the
receipt to the exact paused producer-code hashes. Restore snapshots as new
SSM versions if recovery is needed; repair never enables writers.

Keep `lifecycle.writers_paused=true` through source upgrade, conversion and
readback. After qualification, restore the declared normal setting through
Yoke with both controls false and verify concurrency 5/2/1. [GitHub does not automatically redeliver failed webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries): redeliver failures from the pause before reopening
new CI dispatch. Archive the snapshot and conversion evidence with delivery.

Pulumi's [ignoreChanges contract](https://www.pulumi.com/docs/iac/concepts/resources/options/ignorechanges/)
uses previous state values on updates; refresh and hash verification are
required to prove they match deployed producers. New resources have no old
state to freeze, so the existing-fleet pause procedure refuses writer creates.
