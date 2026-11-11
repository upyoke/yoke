# Web Application Environment Setup

Each environment stack combines an existing VPS stack with managed Postgres,
the API edge, an origin role and instance profile, logs, and a private artifact
bucket. Optional settings add distribution publishing, a GitHub App secret,
and wildcard preview DNS permissions.

## Stack file

Each environment stack is a checked-in `infra/Pulumi.<stack>.yaml` whose
name is the environment's `pulumi.stack_name` in Yoke; the Pulumi Foundation
Pack's `stacks.md` describes the convention. It sets
`webapp-infra:stack_kind: environment`, and `yoke:github_access: variables`
when the environment publishes a distribution (that writes repository
variables); otherwise leave `yoke:github_access` unset.

Yoke supplies the environment's own facts under `yoke:`. Required:
`deploy_namespace`, `environment`, `api_host`, `origin_host`,
`api_origin_port`, `origin_vps_stack_name`, `database_name`. Optional:
`distribution_bucket_name`, `distribution_origin_id` (default
`<namespace>-<environment>-distribution-static`), `distribution_base_url`,
`github_repo_slug`, `github_api_url` (default `https://api.github.com`),
`github_app_private_key_secret_arn`, `github_app_kms_key_arn`,
`ephemeral_preview_domain`.

The project's own `webapp-infra:` keys:

| Key | Required | Meaning |
|---|---|---|
| `stack_kind` | yes | `environment` |
| `domain_name` | yes | The apex domain |
| `hosted_zone_id` | yes | The hosted zone that holds the API records |
| `database_master_username` | yes | The Aurora master username |
| `database_engine_version` | yes | The Aurora PostgreSQL engine version |
| `database_min_capacity_acu`, `database_max_capacity_acu` | yes | Serverless capacity bounds |
| `database_backup_retention_days` | yes | Automated backup retention |
| `database_seconds_until_auto_pause` | no, default `1800` | Idle time before the database pauses |
| `database_allowed_security_group_ids` | no, default `[]` | JSON array of extra groups allowed to reach the database |
| `container_repository_name` | no, default `<namespace>-core` | The ECR repository the origin pulls from |
| `distribution_repository_variable_namespace` | when distributing | Prefix of the distribution repository variables |
| `origin_vps_elastic_ip_output` | no, default `vpsElasticIpAddress` | VPS stack output holding the origin address |
| `origin_vps_security_group_output` | no, default `vpsSecurityGroupId` | VPS stack output holding the origin security group |

With `yoke:distribution_bucket_name` set, the stack refuses unless
`distribution_base_url`, `github_repo_slug` and
`distribution_repository_variable_namespace` are also present.

## Operating the stack

Use Yoke's capability-owned Pulumi command for preview, apply, and refresh:

    yoke pulumi exec --project <project> --stack <stack> -- preview
    yoke pulumi exec --project <project> --stack <stack> -- up --yes --non-interactive
    yoke pulumi exec --project <project> --stack <stack> -- refresh

Review every proposed cloud change before applying it and require a clean
refresh preview afterward.

## Artifact retention

The artifact bucket carries no lifecycle expiry. QA evidence under
`qa-artifacts/` and shared files under `shared-files/` stay until someone
deletes them, because verdicts and links keep citing them; a read of evidence
that was deleted reports `evidence_missing`. Applying this version over an
earlier one removes the earlier bucket-wide 365-day expiry rule. A project
that moves deploy payloads through this bucket under its own
`delivery_authority` prefixes owns their expiry.

## Project-specific work

- Choose environment names, domains, database size and retention, and write
  them into the environment's stack file.
- Create or import the referenced VPS stack and confirm its output names.
- Decide which security groups may reach the database and which repositories
  or distribution buckets the origin may access.
- Configure backup, restore, deletion protection, maintenance windows, alarms,
  incident response, and environment recovery for the real product.
- Review IAM and bucket policies against the project's data classification.
- Import existing cloud resources with their exact provider identifiers rather
  than creating duplicates.
