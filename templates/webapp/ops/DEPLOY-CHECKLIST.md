<!-- YOKE:DEPLOY-CHECKLIST:START - generated template material; refresh through Yoke template/onboarding surfaces -->
# {{project_display_name}} — Environment Infrastructure Checklist

One-time setup checklist for hostname-based ephemeral and preview environments.
See [DEPLOY.md](DEPLOY.md) for the day-to-day deployment runbook.

## Project Settings Requirements

The following values must be set in DB site/environment settings or project
capabilities before materializing project-specific ops files. These feed the
project onboarding and deployment surfaces:

| Key | Example | Used By |
|-----|---------|---------|
| `domain` | `{{domain_name}}` | nginx server_name, TLS cert, workflow URL output |
| `port_base` | `{{port_base}}` | ephemeral_port.js, nginx port computation |
| `port_range` | `{{port_range}}` | ephemeral_port.js, max concurrent ephemeral envs |
| `dns_provider` | `{{dns_provider}}` | provision-tls.sh certbot plugin selection |
| `ssh_host` | `{{origin_ip}}` (Elastic IP from {{pulumi_vps_stack_name}} stack) | VPS commands in runbook |
| `ssh_user` | `{{ssh_user}}` | VPS commands in runbook (Ubuntu EC2 AMIs default to 'ubuntu') |

The `ssh` project capability must also exist with `user` and `host` fields
for the renderer to substitute `{{ssh_user}}` and `{{origin_ip}}`.

## Infrastructure Setup

### 0a. Confirm `aws-admin` capability is populated

Yoke stores AWS credentials per-project in the `aws-admin` capability. Confirm
the capability exists and import secrets through the product CLI:

```sh
yoke projects capability has --project {{project_name}} --cap-type aws-admin --json
yoke projects capability-secret set --project {{project_name}} --cap-type aws-admin --key access_key_id --value-stdin
yoke projects capability-secret set --project {{project_name}} --cap-type aws-admin --key secret_access_key --value-stdin
```

Record non-secret provider settings through project onboarding or a product CLI
Project Structure patch:

```sh
yoke project-structure patch apply --project {{project_name}} --ops-json '<json-ops>'
```

For operator-attended manual AWS CLI checks, use a short-lived provider profile
or SSO session with the same project permissions. Do not scrape Yoke
capability secrets into shell env:

```sh
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} aws sts get-caller-identity
```

### 0b. Bootstrap the Pulumi state backend (once per AWS account/region)

Pulumi stores stack state in an S3 bucket and encrypts secret config values
with a KMS key. Run these in order — bucket first (so versioning is enabled
before any state lands), KMS key + alias next, bucket encryption after the alias
exists, then `pulumi login` and the two `pulumi stack init` calls:

- [ ] `aws s3api create-bucket --bucket {{state_bucket}} --region {{aws_region}}`
- [ ] `aws s3api put-bucket-versioning --bucket {{state_bucket}} --versioning-configuration Status=Enabled`
- [ ] `aws kms create-key --description "Pulumi state encryption for {{project_name}}"`
- [ ] `aws kms create-alias --alias-name {{kms_key_alias}} --target-key-id <key-id-from-prior-step>`
- [ ] `aws s3api put-bucket-encryption --bucket {{state_bucket}} --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"{{kms_key_alias}}"},"BucketKeyEnabled":true}]}'`
- [ ] `pulumi login s3://{{state_bucket}}?region={{aws_region}}`
- [ ] `pulumi stack init {{pulumi_infra_stack_name}} --secrets-provider awskms://{{kms_key_alias}}?region={{aws_region}}`
- [ ] `pulumi stack init {{pulumi_vps_stack_name}} --secrets-provider awskms://{{kms_key_alias}}?region={{aws_region}}`
- [ ] Read `<render-output>/infra/import-plan.md` for the resolved provider IDs before running `pulumi import` commands.

### 0c. Provision the VPS via Pulumi

Both `{{pulumi_infra_stack_name}}` (CloudFront/ACM/Route53) and
`{{pulumi_vps_stack_name}}` (EC2/EIP/SG) live in `<render-output>/infra/`. Apply
them in order with credentials sourced from the `aws-admin` capability:

```sh
cd <render-output>/infra
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} pulumi up --stack {{pulumi_infra_stack_name}} --yes
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} pulumi up --stack {{pulumi_vps_stack_name}} --yes
```

Capture the Elastic IP via
`pulumi stack output vps_elastic_ip --stack {{pulumi_vps_stack_name}}` and apply
it to:

- The `ssh` project capability's `host` field (DB; merge preserves the
  other keys):
  `yoke project-structure patch apply --project {{project_name}} --ops-json '<json-ops>'`

Re-render after both writes:

```sh
yoke templates fetch webapp --dest scratch/webapp-template --force
```

### 0d. (domain-owning projects) Create the hosted zone

Only for projects that declare a `domain` stack in
`sites.settings.pulumi.stacks`. Run the domain stack *before* infra — infra imports the zone it
creates.

- [ ] Operator: register the apex domain in the AWS Route 53 **console** (the
      purchase is a manual click-through; IaC cannot complete it).
- [ ] `pulumi up --stack {{project_name}}-domain --yes`
- [ ] Capture the zone id: `pulumi stack output hostedZoneId --stack {{project_name}}-domain`
- [ ] Record it in DB domain settings and the `aws-route53` capability, then
      refresh project-owned Pulumi material through onboarding or template fetch.
- [ ] (Optional, after registration completes) set `manage_registration=true`,
      re-render, and re-run the domain stack to manage NS + auto-renew.

### 1. Bootstrap the EC2 host

The provisioning script installs Docker, docker-compose plugin, nginx,
`libnginx-mod-http-js`, certbot, and `certbot-dns-route53`. Run it as root.

```sh
yoke templates fetch webapp --dest scratch/webapp-template --only ops/ --force
scp <render-output>/ops/provision-ec2.sh {{ssh_user}}@{{origin_ip}}:/tmp/
ssh {{ssh_user}}@{{origin_ip}} 'sudo sh /tmp/provision-ec2.sh'
```

The script is idempotent — a second invocation is a no-op.

**Verify:**

```sh
ssh {{ssh_user}}@{{origin_ip}} '\
  docker --version && \
  docker compose version --short && \
  nginx -v && \
  nginx -V 2>&1 | grep -q http-js && echo "njs module: present" && \
  certbot --version'
```

### 2. Wildcard DNS

Add a wildcard A record pointing to the Elastic IP.

**Route53 (via AWS CLI):**

```sh
AWS_PROFILE=<operator-profile> AWS_DEFAULT_REGION={{aws_region}} aws route53 change-resource-record-sets \
  --hosted-zone-id {{hosted_zone_id}} \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "*.{{domain_name}}",
        "Type": "A",
        "TTL": 300,
        "ResourceRecords": [{"Value": "{{origin_ip}}"}]
      }
    }]
  }'
```

**Verify:** `dig +short test.{{domain_name}}` should return `{{origin_ip}}`.

The `{{origin_host}}` A record (production hostname) is also flipped via
`aws route53 change-resource-record-sets` in the same window — the
`{{pulumi_vps_stack_name}}` stack does NOT manage that record.

### 3. Wildcard TLS Certificate

**Step 1: Render ops files:**

```sh
yoke templates fetch webapp --dest scratch/webapp-template --only ops/ --force
```

**Step 2: AWS credentials for Route53 DNS-01.**

The EC2 instance has an IAM instance profile (`AmazonSSMManagedInstanceCore`),
but that profile does NOT grant Route53 write access. certbot needs explicit
AWS credentials for the DNS-01 challenge. Provide them via:

- `/root/.aws/credentials` (root-readable, mode 600), OR
- environment variables `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`

The IAM policy needs `route53:ListHostedZones`, `route53:GetChange`,
`route53:ChangeResourceRecordSets`.

**Step 3: Copy and run the provisioning script:**

```sh
scp <render-output>/ops/provision-tls.sh {{ssh_user}}@{{origin_ip}}:/tmp/
ssh {{ssh_user}}@{{origin_ip}} 'sudo sh /tmp/provision-tls.sh'
```

**Verify:** `sudo ls /etc/letsencrypt/live/{{domain_name}}/` shows `fullchain.pem` and `privkey.pem`.

**Manual fallback:**

```sh
sudo certbot certonly --dns-route53 \
  -d "*.{{domain_name}}" -d "{{domain_name}}"
sudo certbot renew --deploy-hook "systemctl reload nginx"
```

### 4. nginx Convention-Based Routing

**Step 1: Render ops files** (if not already done).

**Step 2: Confirm the http-js module is installed** (provision-ec2.sh handles this):

```sh
ssh {{ssh_user}}@{{origin_ip}} 'nginx -V 2>&1 | grep -q http-js && echo OK'
```

**Step 3: Deploy njs module and nginx config:**

```sh
scp <render-output>/ops/ephemeral_port.js {{ssh_user}}@{{origin_ip}}:/tmp/
ssh {{ssh_user}}@{{origin_ip}} 'sudo mkdir -p /etc/nginx/njs.d && sudo cp /tmp/ephemeral_port.js /etc/nginx/njs.d/'
scp <render-output>/ops/nginx-ephemeral.conf {{ssh_user}}@{{origin_ip}}:/tmp/
ssh {{ssh_user}}@{{origin_ip}} 'sudo cp /tmp/nginx-ephemeral.conf /etc/nginx/sites-available/{{project_name}}-ephemeral'
ssh {{ssh_user}}@{{origin_ip}} 'sudo ln -sf /etc/nginx/sites-available/{{project_name}}-ephemeral /etc/nginx/sites-enabled/'
ssh {{ssh_user}}@{{origin_ip}} 'sudo nginx -t && sudo systemctl restart nginx'
```

**Public-IP listener.** The nginx config binds to `{{origin_ip}}:443` (the
Elastic IP) explicitly so other listeners that bind to `0.0.0.0:443`
(if any) do not conflict. Verify with `ss -tlnp | grep 443`.

**Verify:** `sudo nginx -t` passes; `curl -sI https://test.{{domain_name}}` returns HTTP (502 = expected if no container).

**How convention routing works:**

1. Request arrives at `{slug}.{{domain_name}}`
2. nginx extracts the subdomain via regex capture
3. njs computes: `port = {{port_base}} + (parseInt(sha256(slug).substring(0,8), 16) % {{port_range}})`
4. nginx proxies to `127.0.0.1:{port}`

Stateless — routing survives VPS reboots; no per-deploy config files.

### 5. VPS Maintenance

**Install maintenance scripts:**

```sh
yoke templates fetch webapp --dest scratch/webapp-template --only ops/ --force
scp <render-output>/ops/setup-vps-maintenance.sh {{ssh_user}}@{{origin_ip}}:~/
scp <render-output>/ops/ephemeral-cleanup.sh {{ssh_user}}@{{origin_ip}}:~/
ssh {{ssh_user}}@{{origin_ip}} 'chmod +x ~/ephemeral-cleanup.sh && sh ~/setup-vps-maintenance.sh'
```

Installs three cron entries:
- Daily (4:00 UTC): `docker builder prune -f --filter "until=48h"`
- Weekly (Yoke 4:30 UTC): aggressive image/cache prune
- Every 6 hours: `ephemeral-cleanup.sh` (removes stale envs older than {{ephemeral_ttl_hours}}h)

**Verify:**

```sh
ssh {{ssh_user}}@{{origin_ip}} 'crontab -l'
```

**Manual emergency cleanup:**

```sh
ssh {{ssh_user}}@{{origin_ip}} 'docker system prune -af --volumes'
```

Warning: removes ALL unused images, containers, networks, volumes.
