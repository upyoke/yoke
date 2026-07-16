<!-- YOKE:DEPLOY:START - generated template material; refresh through Yoke template/onboarding surfaces -->
# {{project_display_name}} Domain + CDN Deployment Runbook

Operator guide for {{project_display_name}}'s public domain infrastructure.

## Architecture

```
User -> https://{{domain_name}}
     -> CloudFront ({{cloudfront_id}}, SSL termination, www redirect)
     -> HTTP -> nginx port 80 on {{origin_host}} ({{origin_ip}})
     -> proxy_pass -> localhost:{{web_port}} ({{project_display_name}} app)
```

Both stacks live in the rendered `<render-output>/infra/` Pulumi-Python project:

- `{{pulumi_infra_stack_name}}` — CloudFront distribution, ACM cert (imported
  or managed), Route53 alias records, www-to-apex redirect function. Unchanged
  by the EC2 migration.
- `{{pulumi_vps_stack_name}}` — EC2 instance + Elastic IP + security group.
  Access is SSH-only via the key pair named in `{{vps_ssh_key_name}}`. The
  origin host A record is NOT managed by the stack; it is flipped to the
  Elastic IP via `aws route53 change-resource-record-sets` during cutover so
  `pulumi up` completes before traffic moves.

## Current State

| Resource | Value |
|----------|-------|
| Domain | {{domain_name}} |
| CloudFront | {{cloudfront_domain}} ({{cloudfront_id}}) |
| Hosted Zone | {{hosted_zone_id}} |
| ACM Cert | {{certificate_arn}} |
| Origin | {{origin_host}} -> {{origin_ip}} |
| Pulumi Stacks | {{pulumi_infra_stack_name}}, {{pulumi_vps_stack_name}} ({{aws_region}}, account {{aws_account_id}}) |
| State Backend | s3://{{state_bucket}}?region={{aws_region}} (KMS alias {{kms_key_alias}}) |
| VPS | {{vps_description}} |

## Pulumi State Backend Bootstrap

Pulumi keeps stack state in an S3 bucket and encrypts secret config values via
a KMS key. Bootstrap order matters — create and encrypt the bucket first, then
point Pulumi at the backend before any `pulumi stack init`:

```sh
aws s3api create-bucket --bucket {{state_bucket}} --region {{aws_region}}
aws s3api put-bucket-versioning --bucket {{state_bucket}} \
  --versioning-configuration Status=Enabled
aws kms create-key --description "Pulumi state encryption for {{project_name}}"
aws kms create-alias --alias-name {{kms_key_alias}} \
  --target-key-id <key-id-from-prior-step>
aws s3api put-bucket-encryption --bucket {{state_bucket}} \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"{{kms_key_alias}}"},"BucketKeyEnabled":true}]}'
pulumi login s3://{{state_bucket}}?region={{aws_region}}
pulumi stack init {{pulumi_infra_stack_name}} \
  --secrets-provider awskms://{{kms_key_alias}}?region={{aws_region}}
pulumi stack init {{pulumi_vps_stack_name}} \
  --secrets-provider awskms://{{kms_key_alias}}?region={{aws_region}}
```

The bucket name, KMS alias, and per-stack names are project-scoped — re-run
this block only once per AWS account/region. `pulumi login` is idempotent.

Concrete `pulumi import` commands with resolved provider IDs live in
`<render-output>/infra/import-plan.md`.

### Pulumi config keys

These `webapp-infra:<key>` values are Yoke-owned: project onboarding
materializes each stack's `config:` block from DB-backed project, site,
environment, and capability settings. All keys are required; names use
snake_case:

| Key | Type | Stack | Notes |
|---|---|---|---|
| `project_name` | string | all | Resource naming prefix |
| `domain_name` | string | infra, domain | Apex domain |
| `manage_registration` | bool | domain | Optional (default false). false = create the hosted zone only; true = also manage the already-registered domain's name servers + auto-renew |
| `domain_txt_records` | JSON array | infra, domain | Rendered from `sites.settings.domains[].txt_records`; use for domain ownership TXT records. The domain stack owns them when present, otherwise infra does |
| `domain_mx_records` | JSON array | infra, domain | Rendered from `sites.settings.domains[].mx_records`; each record may declare `priority` + `value`, or full Route 53 MX `values`. The domain stack owns them when present, otherwise infra does |
| `origin_host` | string | infra | VPS hostname (a domain, not an IP) |
| `hosted_zone_id` | string | infra | Route 53 hosted zone Id. **Output of the domain stack** — the domain stack creates the zone; infra imports it by id |
| `certificate_arn` | string | infra | ACM cert ARN (us-east-1) |
| `origin_id` | string | infra | CloudFront origin logical Id — reuse the existing Id when importing a live distribution |
| `vps_instance_type` | string | vps | EC2 instance type |
| `vps_root_volume_gb` | int | vps | EBS root volume size in GB |
| `vps_ssh_key_name` | string | vps | EC2 key-pair name |

Only the keys for stacks this project declares in `sites.settings.pulumi.stacks`
are required. A DNS-only project (`stacks: ["domain"]`) needs just `project_name`
+ `domain_name` (+ optional `manage_registration`, `txt_records`, and
`mx_records`).

To change a value, update DB site/environment settings or project capability
settings through onboarding or product CLI Project Structure surfaces, then
refresh project-owned Pulumi material. Inspect resolved values with `pulumi
config --stack <stack>`.

## Quick Commands

### Deploy the domain stack (zone first)

For a project that owns its domain, the domain stack runs **before** infra —
infra imports the hosted zone the domain stack creates. Domain registration
itself is an operator step that IaC cannot fully drive.

1. **Operator (console, one-time):** register the apex domain in the AWS Route
   53 console. TLD availability, registrant contact, and payment are a manual
   click-through; there is no API that completes a purchase end-to-end.
   Registering *through* Route 53 also **auto-creates a public hosted zone**
   the domain delegates to — capture its id and record it in DB domain settings
   so the stack adopts that zone instead of creating a duplicate:

   ```sh
   AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} \
     aws route53 list-hosted-zones --query "HostedZones[?Name=='{{domain_name}}.'].Id" --output text
   # → set hosted_zone_id/importZoneId in DB domain settings, then re-render.
   ```

2. **Create or adopt the hosted zone (Pulumi):** with `importZoneId` set the
   stack adopts the existing zone; without it, it creates a fresh one. Preview
   first to confirm adopt-not-create, then apply:

   ```sh
   cd <render-output>/infra
   pulumi preview --stack {{project_name}}-domain
   pulumi up --stack {{project_name}}-domain --yes
   ```

3. **Hand-back (consumed by every later DNS step):** capture the created zone
   id and record it so infra / ACM / CloudFront can import it:

   ```sh
   pulumi stack output hostedZoneId --stack {{project_name}}-domain
   # → write the value into DB domain settings and the project's aws-route53
   #   capability, then refresh project-owned Pulumi material.
   ```

4. **After registration completes (optional):** set
   `manage_registration=true` in DB domain settings, re-render, and re-run the
   domain stack so Pulumi points the registration's name servers at the zone and
   manages auto-renew. Until then the zone exists and is fully usable; only the
   registration record is unmanaged.

### Deploy both stacks

Apply through the Yoke-owned deploy flow when available. For
operator-attended manual Pulumi runs, use a short-lived provider profile or SSO
session with the same project permissions recorded in the `aws-admin`
capability; do not scrape Yoke capability secrets into shell env.

```sh
cd <render-output>/infra
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} pulumi up --stack {{pulumi_infra_stack_name}} --yes
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} pulumi up --stack {{pulumi_vps_stack_name}} --yes
```

Apply one stack at a time so the VPS stack reads the Elastic IP output of
the infra stack reliably. Preview the diff first with
`pulumi preview --stack <stack>`.

After the VPS stack creates the Elastic IP, capture the Elastic IP output via
`pulumi stack output vps_elastic_ip --stack {{pulumi_vps_stack_name}}`,
write it to the `ssh` project capability's `host` field, then re-render:

```sh
yoke templates fetch webapp --dest scratch/webapp-template --force
```

### Bootstrap a fresh EC2 host

```sh
# Render ops files first
yoke templates fetch webapp --dest scratch/webapp-template --only ops/ --force

# Upload + run the bootstrap as root
scp <render-output>/ops/provision-ec2.sh {{ssh_user}}@{{origin_ip}}:/tmp/
ssh {{ssh_user}}@{{origin_ip}} 'sudo sh /tmp/provision-ec2.sh'
```

### Verify deployment

```sh
# Regenerate the rendered ops scripts under <render-output>/ops/
# (they are generated artifacts, so they must be rendered before use).
yoke templates fetch webapp --dest scratch/webapp-template --only ops/ --force

sh <render-output>/ops/verify-deployment.sh {{domain_name}} {{origin_ip}}
```

### Image lifecycle

Production and hotfix workflows reclaim dangling build generations only after
the API, web, and smoke health gates pass. Cleanup retries three times and then
fails the run: a healthy application plus failed disk reclamation is not a
green deployment. Re-running is safe because Docker never prunes an image
referenced by a container.

On a shared host, never use global `docker image prune -a` as routine
maintenance: it also deletes tagged images intentionally cached for a future
roll. Use the rendered repository-scoped helper instead and explicitly keep
any not-yet-running pin:

```sh
python3 <render-output>/ops/docker_image_cleanup.py \
  --repository registry.example.com/{{project_name}} \
  --keep registry.example.com/{{project_name}}:<next-release-tag>
```

The helper protects images referenced by running or stopped containers,
validates every `--keep` reference before deleting anything, retries transient
Docker failures, and exits nonzero if cleanup cannot converge.

The rendered `docker_maintenance_converge.py` is the single authority for the
weekly cron entry. `setup-vps-maintenance.sh` invokes it during initial setup;
the rendered production and hotfix lanes upload and invoke it again before any
service mutation, so older hosts automatically replace legacy global
`image prune -a` jobs without operator repair.

### Update VPS firewall (restrict to CloudFront IPs)

```sh
# Ensure the ops scripts are rendered locally first.
yoke templates fetch webapp --dest scratch/webapp-template --only ops/ --force

# Preview rules
ssh {{ssh_user}}@{{origin_ip}} 'curl -s https://ip-ranges.amazonaws.com/ip-ranges.json' | \
  sh <render-output>/ops/update-firewall.sh --format ufw

# Or run on VPS directly
scp <render-output>/ops/update-firewall.sh {{ssh_user}}@{{origin_ip}}:/tmp/
ssh {{ssh_user}}@{{origin_ip}} 'sh /tmp/update-firewall.sh --apply'
```

### Check stack status

```sh
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} \
  pulumi stack --stack {{pulumi_infra_stack_name}} --show-urns

AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} \
  pulumi stack --stack {{pulumi_vps_stack_name}} --show-urns
```

`pulumi stack --show-urns` lists every resource with its current state; pair
with `pulumi refresh --stack <stack>` to reconcile drift against AWS.

An environment with distribution settings also converges the complete GitHub
Actions publishing contract from the same Pulumi state: base URL, bucket,
CloudFront distribution ID, and origin ID. The environment setting
`distribution.repository_variable_namespace` explicitly names the product
prefix consumed by the release workflow, which may differ from the project
that owns the deployment stack. Existing repository variables must
be imported into the matching environment stack before apply, using the exact
provider and parent references emitted by `pulumi preview --import-file`; a
manual repository-variable value is not an independent authority.

### Check cert status

```sh
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} \
  aws acm describe-certificate \
  --certificate-arn {{certificate_arn}} \
  --region {{aws_region}} --query 'Certificate.Status' --output text
```

### Break-glass access

If SSH is unavailable (lost key, security-group misconfiguration), the
environment stack attaches AWS Session Manager access to the origin instance
role, so use provider-native session access first. If Session Manager is
unavailable, reconcile the Pulumi environment stack before treating manual
role/profile attachment as emergency drift. SSH remains available through the
configured key pair and security group.

## Ephemeral Environments

Branch pushes trigger ephemeral deploys at hostname-based URLs:

```
https://{branch-slug}.{{domain_name}}
```

For example, branch `feature-login` deploys to `https://feature-login.{{domain_name}}`.

The reverse proxy (nginx) routes `*.{{domain_name}}` subdomains to the correct
container port. Port hashing remains as an internal detail for container port
assignment — it is not exposed in URLs.

### Preview Environments

Named preview environments (e.g., staging, billing) use the same hostname model:

```
https://{preview-name}.{{domain_name}}
```

For example: `https://stage.{{domain_name}}`, `https://billing.{{domain_name}}`.

## VPS Access

```sh
ssh {{ssh_user}}@{{origin_ip}}
```

Sudo password: see `~/{{project_name}}/CREDENTIALS.md`

### nginx config

```sh
# View
ssh {{ssh_user}}@{{origin_ip}} 'cat /etc/nginx/sites-available/{{project_name}}'

# Edit and reload
ssh {{ssh_user}}@{{origin_ip}}
sudo vi /etc/nginx/sites-available/{{project_name}}
sudo nginx -t && sudo systemctl reload nginx
```

## Hostname-Based Environment Infrastructure

For one-time DNS, TLS, nginx, and maintenance setup, see
[DEPLOY-CHECKLIST.md](DEPLOY-CHECKLIST.md).

### Project Config Requirements

The required render values must be present in DB site/environment settings and
project capabilities. See [DEPLOY-CHECKLIST.md](DEPLOY-CHECKLIST.md) for the
full requirements table.

See [DEPLOY-CHECKLIST.md](DEPLOY-CHECKLIST.md) for complete DNS, TLS, nginx, and VPS maintenance setup steps.

## Teardown

```sh
cd <render-output>/infra
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} pulumi destroy --stack {{pulumi_vps_stack_name}} --yes
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} pulumi destroy --stack {{pulumi_infra_stack_name}} --yes
```

`{{pulumi_vps_stack_name}}` destroys the EC2 instance, Elastic IP, security group,
and IAM role. `{{pulumi_infra_stack_name}}` removes the CloudFront distribution +
DNS alias records. Neither stack removes the hosted zone, the imported ACM
cert, or the origin host A record (managed manually via `aws route53`) — those
are marked `protect=True` on the imported Pulumi resources and require an
explicit `pulumi state unprotect` before they can be destroyed.

For the broader "full rebuild after the VPS is unrecoverable" sequence (root
volume corrupted, instance accidentally terminated, etc.), see
[`RECOVERY.md`](RECOVERY.md). The recovery runbook
covers snapshot capture, `.env` preservation, `pulumi state unprotect` sweeping,
the EIP-changes-on-recreate gotcha, the `{{project_name}}-data` Docker volume
restore procedure, TLS re-issuance under rate-limit constraints, and recommends
practicing the whole flow on a disposable staging stack first.
