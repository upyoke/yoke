# Webapp Template — Environment Setup

Full AWS, Pulumi, CloudFront, and nginx setup.

## Infrastructure Setup

After instantiating the scaffold (steps 1-13 above), you can optionally
provision domain, CDN, origin, and managed Postgres infrastructure using the
included Pulumi-Python stacks. Legacy stacks keep a custom domain with HTTPS and
CloudFront in front of a VPS; environment stack instances compose database,
origin, and API edge resources for a specific env.

### How It Works

CloudFront sits between users and your origin:

```
User -> CloudFront (HTTPS) -> nginx/API origin -> app/runtime -> Postgres
        api.example.com          origin.example.com      private Aurora
```

The Pulumi infra stack (`{{pulumi_infra_stack_name}}`) creates: CloudFront distribution, CloudFront Function (www->apex redirect), and Route 53 DNS records. The hosted zone, ACM certificate, origin DNS record, and nginx reverse proxy are set up in a pre-flight step before `pulumi up` runs. The companion `{{pulumi_vps_stack_name}}` stack manages the EC2 instance, Elastic IP, and security group.

A project picks which stacks it runs via `sites.settings.pulumi.stacks`
(default `["infra", "vps"]`). A project that owns its domain through this
template can add a **domain stack** (`<project>-domain`): it *creates* the
Route 53 hosted zone (and optionally manages the registration) and exports the
zone id the infra stack imports. A DNS-only project declares just
`["domain"]` and provisions no CloudFront/EC2 — the smallest cloud footprint
for owning a domain as code.

Projects that need a cloud data plane declare `stackInstances`. Each instance
renders `infra/Pulumi.<instance>.yaml` from the environment-stack template and
can be marked `renderOnly` when the file should exist for review but must not be
initialized or applied yet. The environment stack discovers the AWS account's
default VPC and subnets during Pulumi execution, then wires the VPS security
group to Aurora; operators do not paste subnet ids into tracked project config.

### Pulumi Stack Config

Per-stack values live in rendered `infra/Pulumi.<stack>.yaml` files, all under
the shared `webapp-infra:` namespace. The renderer fills these from DB-backed
project, site, environment, and `project_capabilities` settings at render time.
Every key below is read by `config.require(...)` (or a typed
variant); `pulumi up` exits non-zero if any is missing.

| Config key | Type | Read by | Description | Example |
|---|---|---|---|---|
| `project_name` | string | both stacks | Resource naming prefix | `{{project_name}}` |
| `domain_name` | string | infra | Apex domain | `example.com` |
| `origin_host` | string | infra | VPS hostname (**must be a domain, not an IP**) | `origin.example.com` |
| `hosted_zone_id` | string | infra | Route 53 hosted zone Id | `Z0000000000000EXAMPLE` |
| `certificate_arn` | string | infra | ACM certificate ARN (us-east-1 for CloudFront) | `arn:aws:acm:us-east-1:...` |
| `origin_id` | string | infra | CloudFront origin logical Id (pick a stable snake_case value; reuse the existing Id when importing a live distribution so Pulumi does not create a duplicate origin) | `{{project_name}}-origin` |
| `vps_instance_type` | string | vps | EC2 instance type for the VPS stack | `t3.small` |
| `vps_root_volume_gb` | int | vps | EBS root volume size in GB | `30` |
| `vps_ssh_key_name` | string | vps | EC2 key-pair name for SSH access | `{{project_name}}-pulumi` |
| `stack_kind` | string | env | Dispatches composed env stacks | `environment` |
| `environment` | string | env | Stable env label | `prod` |
| `api_host` | string | env | API hostname served by CloudFront | `api.example.com` |
| `api_origin_port` | int | env | HTTP port exposed by the origin | `80` |
| `database_name` | string | env | Initial Postgres database name | `app_prod` |
| `database_master_username` | string | env | Generated master-user secret username | `app_admin` |
| `database_engine_version` | string | env | Aurora PostgreSQL engine version | `16.13` |
| `database_min_capacity_acu` / `database_max_capacity_acu` | number | env | Aurora Serverless v2 capacity range | `0` / `4` |
| `database_seconds_until_auto_pause` | int | env | Aurora Serverless v2 idle seconds before scale-to-zero pause | `1800` |
| `database_backup_retention_days` | int | env | Provider-managed retention window | `7` |
| `database_allowed_security_group_ids` | JSON string list | env | Additional managed services allowed to reach Postgres; the origin VPS security group is always included automatically | `["sg-0123456789abcdef0"]` |
| `render_only` | bool string | env | Generated but intentionally not applied | `true` |

`database_allowed_security_group_ids` is rendered from the authoritative
`environments.settings.database.allowed_security_group_ids` string list.

These values are Yoke-owned: update the canonical DB site/environment
settings or project capability settings through project onboarding or product
CLI project-structure surfaces, then refresh the project-owned Pulumi material.
The rendered stack file is regenerated each run, so direct edits to it do not
persist (the renderer warns before overwriting a diverged value). See
`templates/webapp/SETUP-DEPLOYMENT.md` step 1b for the full key walkthrough. The
hosted zone and ACM certificate are created in the pre-flight steps
(SETUP-DEPLOYMENT §2-5) before `pulumi up` runs; the resolved Ids are then
written into those canonical sources and rendered into the stack config above.

### Prerequisites

- **AWS account** with access to Route 53, CloudFront, ACM, EC2, S3, and KMS.
- **IAM user** with CLI credentials (see IAM setup below).
- **Python 3.10+** for the Pulumi infra modules. On Python 3.14+, pulumi-language-python no longer implicitly adds the Pulumi project directory to `sys.path` when launching `__main__.py`; the template's `templates/webapp/infra/__main__.py` already carries an explicit `sys.path.insert` shim for this, and re-rendered projects inherit it automatically. If a debugger ever reports `ModuleNotFoundError: '<project>_infra_stack'` on a fresh 3.14+ interpreter, confirm the shim block at the top of the rendered `<render-output>/infra/__main__.py` is present — its purpose is exactly that import.
- **Pulumi CLI** installed: see [pulumi.com/docs/install](https://www.pulumi.com/docs/install/).
- **Python deps** for the infra modules: `pip install -r <render-output>/infra/requirements.txt`.
- **Domain registered** in your AWS account (or elsewhere — you will update NS records post-deploy). Registration itself is a manual AWS Route 53 console purchase — TLD availability, registrant contact, and payment cannot be fully automated. The domain stack creates the *hosted zone* as code; the purchase is the operator's console step.
- **VPS with nginx** reverse-proxying port 80 -> your app port.

### Create IAM User

Create a dedicated IAM user for project Pulumi deployments (~2 minutes in the AWS Console).

1. Go to **IAM > Users > Create user**
2. User name: `{{project_name}}-pulumi`
3. Do NOT enable console access (this user is CLI-only)
4. Create an inline policy with the following permissions (minimum required for the webapp Pulumi stacks plus their S3+KMS state backend):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Route53HostedZoneManagement",
      "Effect": "Allow",
      "Action": [
        "route53:CreateHostedZone",
        "route53:DeleteHostedZone",
        "route53:GetHostedZone",
        "route53:ListHostedZones",
        "route53:ChangeResourceRecordSets",
        "route53:GetChange",
        "route53:ListResourceRecordSets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ACMCertificateManagement",
      "Effect": "Allow",
      "Action": [
        "acm:RequestCertificate",
        "acm:DeleteCertificate",
        "acm:DescribeCertificate",
        "acm:ListCertificates",
        "acm:ListTagsForCertificate",
        "acm:AddTagsToCertificate"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudFrontDistributionManagement",
      "Effect": "Allow",
      "Action": [
        "cloudfront:CreateDistribution",
        "cloudfront:DeleteDistribution",
        "cloudfront:GetDistribution",
        "cloudfront:UpdateDistribution",
        "cloudfront:TagResource",
        "cloudfront:UntagResource",
        "cloudfront:ListTagsForResource",
        "cloudfront:CreateFunction",
        "cloudfront:DeleteFunction",
        "cloudfront:DescribeFunction",
        "cloudfront:GetFunction",
        "cloudfront:PublishFunction",
        "cloudfront:UpdateFunction",
        "cloudfront:ListDistributions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EC2VpsStackManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeImages",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:DescribeSecurityGroups",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupIngress",
        "ec2:AllocateAddress",
        "ec2:ReleaseAddress",
        "ec2:AssociateAddress",
        "ec2:DisassociateAddress",
        "ec2:DescribeAddresses",
        "ec2:CreateTags",
        "ec2:DescribeTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RDSAuroraEnvironmentStackManagement",
      "Effect": "Allow",
      "Action": [
        "rds:CreateDBCluster",
        "rds:DeleteDBCluster",
        "rds:ModifyDBCluster",
        "rds:DescribeDBClusters",
        "rds:CreateDBInstance",
        "rds:DeleteDBInstance",
        "rds:DescribeDBInstances",
        "rds:CreateDBSubnetGroup",
        "rds:DeleteDBSubnetGroup",
        "rds:DescribeDBSubnetGroups",
        "rds:AddTagsToResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SecretsManagerDatabaseCredentialRead",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3ForPulumiState",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:GetBucketLocation",
        "s3:GetBucketPolicy",
        "s3:PutBucketPolicy",
        "s3:PutBucketVersioning",
        "s3:GetBucketVersioning",
        "s3:PutEncryptionConfiguration",
        "s3:GetEncryptionConfiguration",
        "s3:PutLifecycleConfiguration",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::{{state_bucket}}",
        "arn:aws:s3:::{{state_bucket}}/*"
      ]
    },
    {
      "Sid": "KMSForPulumiSecretsProvider",
      "Effect": "Allow",
      "Action": [
        "kms:CreateKey",
        "kms:DescribeKey",
        "kms:Encrypt",
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:CreateAlias",
        "kms:DeleteAlias",
        "kms:ListAliases"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IAMForVpsInstanceProfile",
      "Effect": "Allow",
      "Action": [
        "iam:*Role*",
        "iam:*Policy*",
        "iam:PassRole",
        "iam:*InstanceProfile*"
      ],
      "Resource": "arn:aws:iam::*:role/{{project_name}}-*"
    },
    {
      "Sid": "STSForPulumiDeploy",
      "Effect": "Allow",
      "Action": [
        "sts:AssumeRole",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

5. Go to **IAM > Users > {{project_name}}-pulumi > Security credentials**
6. Click **Create access key** > select **Command Line Interface (CLI)**
7. Copy the Access Key ID and Secret Access Key

### Configure AWS Credentials

Store credentials in Yoke's per-project `aws-admin` capability. Do not write
AWS credentials into the repo.

```sh
yoke projects capability-secret set --project {{project_name}} --cap-type aws-admin --key access_key_id --value-stdin
yoke projects capability-secret set --project {{project_name}} --cap-type aws-admin --key secret_access_key --value-stdin
yoke project-structure patch apply --project {{project_name}} --ops-json '<json-ops>'
```

**SECURITY:** Never commit credential files to git. If you suspect credentials
have been committed, rotate them immediately in the AWS Console and update the
capability secrets.

### Credential Rotation

1. Go to **IAM > Users > {{project_name}}-pulumi > Security credentials**
2. Create a new access key
3. Update the `aws-admin` capability secrets
4. Verify with `aws sts get-caller-identity` using DB-sourced env vars
5. Deactivate and delete the old access key
