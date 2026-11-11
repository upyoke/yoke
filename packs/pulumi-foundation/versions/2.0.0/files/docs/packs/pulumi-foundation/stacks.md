# Pulumi Stacks

The Pulumi Foundation Pack supplies composition mechanics; component Packs
supply independently useful infrastructure behavior.

## Stack sources

- pulumi-foundation: project entrypoint, aliases, and GitHub repository
  provider.
- webapp-environment-infrastructure: composition of a deployable environment
  from the VPS, database, registry, API edge, and supporting policies.
- vps-hosting: standalone VPS component.
- domain-cdn-edge: hosted zone, DNS, API edge, certificate, and CDN components.
- registry-oidc: container registry and GitHub Actions federation.
- managed-database: managed Postgres component.
- self-hosted-runners: runner fleet and token-broker components.

Installing pulumi-foundation alone creates no cloud resources.

## Stack files

Every stack is an ordinary checked-in `infra/Pulumi.<stack>.yaml`. No Pack
ships one: the file holds the project's own values, so the project writes it
and owns it. `yoke pulumi exec --project <project> --stack <stack> -- init
--secrets-provider <awskms URI>` prints the `secretsprovider` and
`encryptedkey` lines to commit for a new stack.

The entrypoint picks the component by stack name: a name ending in `-infra`,
`-vps`, `-domain`, `-registry`, or `-runner-fleet`, or any name whose stack
file sets `webapp-infra:stack_kind: environment`.

Values come from two namespaces:

- The project's own values sit under the Pulumi project name, `webapp-infra:`,
  and the programs read them with `pulumi.Config()`. Each component Pack's
  documentation lists the keys its stack needs.
- Values Yoke computes sit under the reserved `yoke:` namespace. `yoke pulumi
  exec` adds them to a private copy of the stack file on every run, and the
  programs read them with `pulumi.Config("yoke")`. A stack file must not set
  them.

The stack file also sets `aws:region` for the AWS provider.

A `<namespace>-vps` stack (the vps-hosting component) reads these
`webapp-infra:` keys: `vps_instance_type`, `vps_root_volume_gb` and
`vps_ssh_key_name` (required), and `vps_iam_instance_profile_name`
(optional; absent leaves the instance without a profile).

### Yoke-supplied values

Every stack receives, when Yoke holds them:

| `yoke:` key | Meaning |
|---|---|
| `deploy_namespace` | The project's stable deployment namespace; every stack requires it |
| `aws_account_id`, `aws_region` | The project's `aws-admin` capability |
| `kms_key_alias` | The `pulumi-state` capability's KMS key alias |
| `component_type_aliases_json` | Legacy component type aliases per stack kind |
| `github_repo_slug`, `github_api_url` | The project's GitHub binding |
| `delivery_authority_json` | The merged per-environment delivery grant |

An environment stack (one an environment's `pulumi.stack_name` names) also
receives `environment`, `api_host`, `origin_host`, `api_origin_port`,
`origin_vps_stack_name`, `database_name`, `distribution_bucket_name`,
`distribution_origin_id`, `distribution_base_url`,
`github_app_private_key_secret_arn`, `github_app_kms_key_arn`, and
`ephemeral_preview_domain`.

Yoke leaves out any value it does not hold. A program that requires one then
fails with Pulumi's missing-config error naming the `yoke:` key; set the
named setting in Yoke and retry rather than writing the key into the file.

### GitHub access level

The one `yoke:` key a stack file may set is `yoke:github_access`, the GitHub
App access the run receives:

| Value | Grants | Use for |
|---|---|---|
| `metadata` (or unset) | metadata read | stacks that manage no GitHub resources |
| `variables` | adds Actions variables write | registry and environment stacks that publish repository variables |
| `runner_fleet` | adds repository hooks write, and the `yoke:runner_fleet_*` values | the runner-fleet stack |

## Authority split

- Pack-installed infra/ files define reusable program behavior.
- The project's checked-in stack files hold its stack selection and
  non-secret values.
- Yoke's project settings hold the values Yoke supplies under `yoke:`.
- Capability secret stores hold provider credentials.
- Pulumi checkpoints describe live resource state.

No layer should impersonate another. In particular, Pack receipts do not store
stack state or secrets, and customized project infrastructure source is not
central drift.

## Updating

Preview and apply one component Pack update at a time, review the merged source,
then run exact-stack Pulumi previews for every affected project stack. A Pack
update is not an infrastructure apply. After moving a stack from an earlier
Pack version, its preview must show no resource changes; a change means a
stack file value is missing or differs from what the stack used before.
