# GitHub App Operations

This runbook owns Yoke's GitHub App registration, installation scope,
private-key custody, hosted and self-hosted bootstrap,
rotation, verification, and incident response. Product flows never ask users to paste a GitHub credential.

## Ownership Boundary

GitHub registration and installation are human trust ceremonies. An App owner
or manager creates the registration, and an account or organization owner
approves each installation and permission increase. Yoke then manages the
repeatable runtime pieces:

- machine device authorization and refresh-token rotation;
- verified installation and repository bindings;
- repository- and operation-scoped installation tokens;
- hosted key delivery from an external secret reference; and
- the optional runner-fleet repository webhook and its HMAC through Pulumi.

The GitHub App private-key secret container and its value are external
bootstrap authority. Pulumi does not create or own them and must receive only a
Secrets Manager ARN. This keeps the PEM out of source, Pulumi config/state,
command arguments, logs, project databases, and machine config.

## Hosted Deploy Relay

Deployment runners are clients of the credential-bearing control plane; they are
not GitHub App hosts. A CI job may receive a project-scoped Yoke API token,
write it through `yoke connection set <relay-env> --transport https
--token-stdin` under a run-scoped `YOKE_MACHINE_HOME`, and select that
connection with `YOKE_GITHUB_ACTIONS_RELAY_ENV`. The deploy pipeline relays
typed workflow dispatch, run lookup, job count, CI check, and run-status calls
through `/v1/functions/call`. The hosted handler resolves a short-lived,
repository-scoped installation token internally.

The deploy actor must hold `deployment_ci` on the project named in the request.
It can dispatch workflows and read the routing variable and run state needed
for deployment reporting. It cannot read the infrastructure render snapshot,
fetch install bundles, sync snapshots, mutate onboarding/backlog/project
settings, write repository configuration, administer runners/webhooks, or
access another project. A separate `infrastructure_ci` actor owns secret-free
render and runner-token authority; never reuse its token for deploy relay.
Owners and org admins retain their permission wildcards.

Workflow dispatch asks GitHub for the exact run id and disables retries on the
non-idempotent POST. Its idempotency key reuses the stage key for resumes,
scopes retriggers to the failed/empty predecessor, and gives `--fresh` a new
scope, so transport replay cannot suppress a deliberately new run.

To narrow a deploy actor that temporarily holds `owner`, deploy/restart so the
catalog removes stale role permissions. Grant the role, verify the relay
preflight, then revoke `owner`:

```bash
YOKE_ENV=prod-db-admin python3 -m yoke_core.domain.actor_grants_cli grant-project \
  --actor <service-actor-id> --project <project> --role deployment_ci
# Run the relay preflight with the existing service token.
YOKE_ENV=prod-db-admin python3 -m yoke_core.domain.actor_grants_cli revoke-project \
  --actor <service-actor-id> --project <project> --role owner
```

Both commands are idempotent. Revoke only after the same token succeeds against
the newly deployed control plane.

`YOKE_GITHUB_ACTIONS_RELAY_ENV` selects HTTPS GitHub authority independently of
`YOKE_ENV`, which may select deployment metadata authority. Missing, malformed,
or non-HTTPS relay selection fails closed. App keys and installation tokens do
not belong in repo secrets, CI environments, runner disks, or workflow logs.

Normal CI and manual deploys set `YOKE_GITHUB_ACTIONS_RELAY_ENV=<https-env>`.
An attended release introducing/repairing the relay may instead set
`YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY=1` and use sanctioned local App authority.
Both selectors, an invalid local value, or neither selector fail pre-dispatch.

## CI Credential Custody

See [GitHub App CI custody](github-app-ci-custody.md) for the runner-token
broker, OIDC role split, explicit App-key denies, and origin-owned key retrieval.

## Registration Checklist

Use a manual registration or a prefilled registration URL for the current
device-flow implementation. A GitHub App manifest is useful only when a trusted
HTTPS redirect can exchange its one-hour code and immediately place the
returned secrets in the operator secret store. Do not use a manifest as a JSON
file containing returned credentials, and do not add a manifest callback that
does not exist.

Set or review these fields:

| Field | Current Yoke contract |
| --- | --- |
| Owner | The organization or account responsible for App and key lifecycle |
| Name/slug | Unique and environment-qualified when registrations are separate |
| Homepage | The operator's real HTTPS product or control-plane homepage |
| Description | GitHub automation for Yoke projects |
| Visibility | Private for owner-only/internal use; public only for an App intended for third-party installation |
| User callback URLs | Leave empty for CLI device flow; add only implemented HTTPS hosted callbacks |
| Setup URL | Leave empty until an implemented hosted installation callback owns it |
| Request authorization on install | Off; Yoke starts user authorization explicitly |
| Device Flow | On |
| Expire user authorization tokens | On |
| App-level webhook | Off until the hosted installation-lifecycle receiver exists |
| Webhook events | None while the App-level webhook is off |

The runner fleet uses a Pulumi-managed **repository webhook**. It is not the
App-level webhook above.

Baseline repository permissions are:

- Actions: write
- Checks: read
- Contents: write
- Issues: write
- Metadata: read
- Pull requests: write
- Secrets: write
- Variables: write
- Workflows: write

Administration and Webhooks (`repository_hooks`) write are privileged runner
fleet extensions. GitHub App permissions apply to the registration and are
presented to every installation; they are not independently optional per
repository. The currently supported compatibility topology is one App for the
canonical project `github` binding, with these privileged extensions added
when that project runs a fleet. Baseline product operations still mint tokens
without Administration or Webhooks; runner operations mint separate,
repository-scoped tokens with only their required permissions. A second
operator-only App is the intended stronger isolation boundary, but verified
multi-binding support has not landed: do not configure a second registration
as a runner capability selector yet.

No GitHub client secret is required. Device authorization and refresh use the
public client id, while server automation signs App JWTs with the private key.
Do not generate, copy, or store a client secret unless a future implemented web
authorization flow explicitly owns it.

## Installation And Repository Scope

Prefer **Only select repositories** and add the repositories each project
actually binds. **All repositories** is an explicit blast-radius decision,
especially for an App with Administration write. A compromised private key can
act outside Yoke's token-scoping code, so runtime downscoping does not make an
all-repository installation equivalent to a selected-repository installation.

After installation or a permission/repository change:

```bash
yoke github status
yoke projects github-binding status --project <project>
```

Re-bind the project when the server's verified installation metadata needs to
be refreshed. The binding stores only non-secret installation, repository,
origin, permission, and status metadata.

## Existing Runner Variable Adoption

The runner stack owns the configured Actions variable. Before the first apply,
run `yoke github-actions runners status --project <project>`. An
`adopt_runner_routing_variable` result means the variable already exists and
Pulumi must adopt it before changing its value; applying first fails loudly on
the GitHub name collision.

The imported resource is a child of the runner-fleet component and uses its
explicit GitHub provider. Both must already exist in stack state. For a new
runner-fleet stack, leave `routing_enabled=false`, render and apply the base
stack once, and confirm a zero-change preview. That base apply creates the
component, provider, webhook, and fleet without managing or changing the
pre-existing variable. Then set `routing_enabled=true` and render again.

From the rendered `infra/` directory, use the same validated settings envelope
and short-lived repository authority as every other runner operation. First
have Pulumi generate the import record from the exact rendered program so the
record carries the correct parent and provider references:

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

The generated preview import file must contain exactly one create after the
base stack is converged: type
`github:index/actionsVariable:ActionsVariable`, name
`runnerFleetRoutingVariable`. Copy only that complete record to
`<runner-variable-import-file.json>`, preserve its generated `parent` and
`provider` fields unchanged, and set its `id` to
`<repository-name>:<variable-name>`. Stop if the candidate is missing, is not
unique, lacks either relationship, or the preview contains a replacement or
delete. Do not use a positional `pulumi import` without `--parent` and
`--provider`; it creates the wrong Pulumi identity for this child resource.

Preview immediately after import and verify the only planned change is the
compact label array, then apply and require a final zero-change refresh
preview. If routing is disabled and status reports
`resolve_runner_routing_variable`, review ownership and deliberately
delete/rename the nonmatching variable, or follow the base-apply and adoption
sequence above before any apply that declares the variable. Absence is the
only clean disabled state. Never repair this path with a direct variable
write.

## Hosted Secret Bootstrap

Create one stable AWS Secrets Manager secret container per intended isolation
boundary. Record ownership and lifecycle with tags such as application,
environment, owner, data classification, and rotation policy. Use the
operator's approved KMS key when policy requires customer-managed encryption,
and grant `secretsmanager:GetSecretValue` only to the deploy authority and
runtime consumers that mint App tokens. Configure a recovery window; do not
force-delete the secret during ordinary replacement or teardown.

Ingest the downloaded PEM through an approved source-dev/admin secret surface
that reads a protected file or stdin. Never interpolate the PEM into a shell
command, pass it as an argument, paste it into Pulumi config, or retain it in a
terminal transcript. Keep the same secret ARN during rotation by adding a new
secret version instead of deleting and recreating the container.

The capability-scoped source-dev/admin shape is:

```bash
yoke aws exec --project <deploy-owner-project> -- \
  secretsmanager create-secret \
  --name <stable-secret-name> \
  --description "Yoke GitHub App private key" \
  --kms-key-id <kms-key-arn-or-alias> \
  --secret-string file://<protected-pem-path> \
  --tags Key=application,Value=yoke Key=classification,Value=secret
```

The PEM contents are read by the AWS CLI from the file and never become an
argument value. The command result contains secret metadata, not the secret
string. Store the returned ARN in the operator-owned environment settings.

Each hosted environment stores only this non-secret reference:

```json
{
  "github_app": {
    "issuer": "<app-client-id-or-numeric-id>",
    "api_url": "https://api.github.com",
    "private_key_secret_arn": "arn:aws:secretsmanager:<region>:<account>:secret:<name>",
    "kms_key_arn": "arn:aws:kms:<region>:<account>:key/<optional-customer-key-id>"
  }
}
```

The secret ARN's region and account must match deployment authority. When the
secret uses a customer-managed KMS key, declare its exact key ARN so the origin
role receives only `kms:Decrypt`/`DescribeKey` on that key. Deployment instructs
the origin to fetch a pending owner-only file through its instance role, pulls
the candidate core image, and verifies authenticated `/app` identity with the
pending file mounted only inside the probe. Success atomically promotes it;
failure removes pending and preserves the prior durable file. CI never receives
the PEM or transports it through SSH stdin.

This pre-delivery check proves the issuer and PEM belong to the same live App.
It does not prove that a particular installation still covers a project's
repositories; use the project health check in the rotation procedure for that
binding-level verification.

The downloaded PEM is transient for hosted bootstrap. Set mode `0600`, compare
its fingerprint with GitHub, ingest and verify it, then remove the download.
Self-hosted deployments retain their runtime copy under the generated bundle's
ignored `secrets/` directory.

## Zero-Downtime Private-Key Rotation

GitHub supports multiple active private keys specifically so rotation can
overlap. Rotate one registration at a time:

1. Inventory every hosted environment, self-hosted server, and runner fleet
   using the App and its secret reference.
2. Generate a second private key in the GitHub App settings. Keep the old key
   active.
3. Protect the download as `0600` and verify its fingerprint against GitHub.
   The source must be a real, single-link file owned by the current operator;
   Yoke refuses symlinks and group/world-accessible sources.

   ```bash
   chmod 600 <protected-new-pem-path>
   ```

4. Put the new PEM into the existing Secrets Manager secret as a new version,
   using file/stdin ingress that does not log or expose the value. For
   self-hosted, use Yoke's atomic ingress; it preserves the bundle and its
   database credentials:

   ```bash
   # Hosted environment:
   yoke aws exec --project <deploy-owner-project> -- \
     secretsmanager put-secret-value \
     --secret-id <existing-secret-arn> \
     --secret-string file://<protected-new-pem-path>

   # Self-hosted bundle:
   yoke self-host init --dir /path/to/yoke-server --protect-existing \
     --github-app-private-key <protected-new-pem-path>
   ```
5. Redeploy every hosted core environment that references the ARN. Recreate the
   self-hosted `core` container so its secret mount uses the replacement file.
   Reconcile each runner-fleet stack through `yoke runner-fleet exec`; its
   Lambdas read the current secret version when minting tokens.
6. Against each control plane, verify a bound project through the server-side
   resolver:

   ```bash
   yoke doctor run --only HC-project-gh-auth --project <project>
   ```

   Also run the runner-fleet smoke path where that privileged capability is
   enabled. A machine-only `yoke github status` verifies user authorization,
   not the hosted private key, so it is not sufficient rotation evidence.
7. Delete the old private key in GitHub only after every consumer is green.
   Repeat the server-side checks once more.
8. Remove transient PEM downloads and record the rotation time, GitHub key
   fingerprint, secret version, environments verified, and operator. Never
   record the PEM or a minted token.

Changing the App private key does not require users to reconnect machine
device authorization. Those refresh credentials have their own automatic
rotation and revocation lifecycle.

## Incident Response

For suspected private-key disclosure, generate and distribute a replacement,
then revoke the affected GitHub key as soon as the new path is verified. If the
risk does not permit an overlap window, revoke immediately and accept temporary
automation downtime. Review installation repository scope and permissions;
suspend or uninstall affected installations when containment requires it.

Rotate the runner repository-webhook HMAC through Pulumi so GitHub's webhook
configuration and the Lambda verifier change together. Do not edit only the SSM
parameter. If a machine refresh credential is exposed, revoke the GitHub user
authorization and run `yoke github disconnect` on the machine before
reconnecting.

Official references:

- [Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app)
- [Registering with URL parameters](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-using-url-parameters)
- [Registering from a manifest](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)
- [Managing private keys](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps)
