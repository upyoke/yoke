# Webapp Template — Deployment Setup

### First-Time Deploy (Full Flow)

The first deployment has extra steps to create resources that the Pulumi stacks will then import. Subsequent deploys skip to "Pulumi up" below.

#### 1. Bootstrap the Pulumi state backend (once per AWS account/region)

Pulumi stores stack state in the S3 backend declared by the project's
`pulumi-state` capability and encrypts secret config values with its KMS key.
The bucket and KMS alias must already exist through the provider-admin setup
path, and every stack below must already be declared in the capability's
`stacks` map. Do not export project AWS credentials, run `pulumi login`, or run
`pulumi stack init` directly.

```sh
yoke projects capability has --project {{project_name}} --cap-type aws-admin --json
```

Initialize every non-render-only declared stack through the capability-owned
boundary. Legacy projects usually have `infra` + `vps`; data-plane projects
also have environment instances declared under
`sites.settings.pulumi.stackInstances`:

```sh
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- init --secrets-provider 'awskms://{{kms_key_alias}}?region={{aws_region}}'
yoke pulumi exec --project {{project_name}} --stack {{pulumi_vps_stack_name}} -- init --secrets-provider 'awskms://{{kms_key_alias}}?region={{aws_region}}'
yoke pulumi exec --project {{project_name}} --stack {{project_name}}-prod -- init --secrets-provider 'awskms://{{kms_key_alias}}?region={{aws_region}}'
```

`yoke pulumi exec` resolves the exact project capability, materializes a 0700
scratch workspace, and persists the initialized stack's typed operator-state.
No repo-local infrastructure checkout or ambient AWS shell environment is
needed.

Do not initialize or apply a generated instance whose rendered config has
`webapp-infra:render_only: "true"`; it is a reviewed artifact for a later
activation step.

#### 1b. Populate Pulumi config keys (Yoke-owned)

`templates/webapp/infra/__main__.py` reads every value below from
`pulumi.Config()`. All keys are required — `pulumi up` exits non-zero if any
is missing. Both stacks share the `webapp-infra:` namespace (set by
`Pulumi.yaml`'s project name), so each config key reads as `webapp-infra:<key>`
in snake_case — `vps_ssh_key_name`, not `vpsSshKeyName`.

**These values are Yoke-owned.** Project onboarding materializes the `config:`
block of each stack file from the project's canonical config sources, so the
safe way to change one is to edit the source through onboarding or product CLI
Project Structure surfaces. Do not hand-edit the rendered stack file; the next
materialize step reverts it and names the recovery path.

The Yoke-owned Pulumi keys live in DB-backed settings: `sites.settings.pulumi`
for stack declarations and Pulumi-specific fields (`originId`, stack names, and
environment-instance config values such as `api_host`, `origin_host`, and
`database_*`), `sites.settings.domains` for domain/certificate/hosted-zone
facts, `environments.settings` for env-specific hosts/data-plane settings, and
project capabilities for provider/runtime facts. Edit the Yoke-owned source
through project onboarding or product CLI project-structure surfaces, then
refresh the project-owned Pulumi material:

```sh
yoke templates fetch webapp --dest scratch/webapp-template --only infra/ --force
```

Key reference (every entry maps to a `config.require(...)` / `config.require_int(...)` call in `templates/webapp/infra/__main__.py`):

| Key | Type | Read by | Notes |
|---|---|---|---|
| `project_name` | string | both stacks | Resource naming prefix. Match `{{project_name}}`. |
| `domain_name` | string | infra | Apex domain managed by CloudFront. |
| `origin_host` | string | infra | VPS hostname (a domain, not an IP). |
| `hosted_zone_id` | string | infra | Route 53 hosted zone Id (created in §2 below). |
| `certificate_arn` | string | infra | ACM cert ARN (us-east-1; created in §5 below). |
| `origin_id` | string | infra | CloudFront origin logical Id — see below. |
| `vps_instance_type` | string | vps | EC2 instance type (`t3.small`, etc). |
| `vps_root_volume_gb` | int | vps | EBS root volume size in GB. |
| `vps_ssh_key_name` | string | vps | EC2 key-pair name for SSH. |
| `stack_kind` | string | env | `environment` dispatches the composed env stack. |
| `environment` | string | env | Stable env label such as `prod` or `stage`. |
| `origin_vps_stack_name` | string | env | Pulumi stack name of the separately applied standalone VPS serving this environment. |
| `origin_vps_elastic_ip_output` | string | env | Renderer-owned Elastic IP output name on the standalone VPS stack. |
| `origin_vps_security_group_output` | string | env | Renderer-owned security-group output name on the standalone VPS stack. |
| `api_host` / `origin_host` | string | env | Public API hostname and sibling origin hostname. |
| `api_origin_port` | int | env | Origin listener port behind CloudFront. |
| `database_*` | mixed | env | Database name, master username, engine version, ACU range, and backup retention. |
| `render_only` | bool string | env | Generated for review; do not `stack init` or `up` while true. |

`origin_id` controls the CloudFront origin's logical Id. **For fresh
distributions**, pick any stable snake_case string (for example
`{{project_name}}-origin`); the value is durable — once `pulumi up` creates
the distribution, renaming `origin_id` forces a CloudFront origin replace
on the next apply. **When importing an existing distribution into Pulumi**,
set `origin_id` to the distribution's existing origin Id (visible under
`Origins → Origin ID` in the CloudFront console, or via
`aws cloudfront get-distribution-config --id <dist-id>` → `Origins.Items[0].Id`)
so Pulumi reconciles against the live state instead of creating a duplicate
origin. The infra stack rejects empty / missing values at config-load time;
there is no runtime default.

Confirm every key resolved:

```sh
pulumi config --stack {{pulumi_infra_stack_name}}
pulumi config --stack {{pulumi_vps_stack_name}}
pulumi config --stack {{project_name}}-prod
```

#### 2. Create Route 53 hosted zone

If your domain was registered via Route 53, a hosted zone already exists. Otherwise:

```sh
aws route53 create-hosted-zone --name example.com --caller-reference "$(date +%s)"
```

Note the hosted zone ID from the output. If the domain was registered via Route 53 and an auto-created zone exists, use that zone's ID.

#### 3. Point domain NS records to the hosted zone

If registered via Route 53, NS records are set automatically. Otherwise, update your registrar's NS records to match the hosted zone's name servers:

```sh
aws route53 get-hosted-zone --id ZXXXXXXXXX --query 'DelegationSet.NameServers'
```

**Important:** Delete any duplicate hosted zones. Only one hosted zone per domain should exist, and NS records must point to it. Duplicate zones are the #1 cause of ACM validation failures.

#### 4. Create origin DNS record

CloudFront requires a domain name (not an IP) as the origin. Create an A record for your VPS:

```sh
aws route53 change-resource-record-sets --hosted-zone-id ZXXXXXXXXX --change-batch '{
  "Changes": [{"Action":"CREATE","ResourceRecordSet":{
    "Name":"origin.example.com","Type":"A","TTL":300,
    "ResourceRecords":[{"Value":"YOUR_VPS_IP"}]
  }}]
}'
```

#### 5. Request ACM certificate and add validation CNAMEs

```sh
# Request cert (must be us-east-1 for CloudFront)
aws acm request-certificate --domain-name example.com \
  --subject-alternative-names www.example.com \
  --validation-method DNS --region us-east-1

# Get validation CNAME records from the cert
aws acm describe-certificate --certificate-arn ARN --region us-east-1 \
  --query 'Certificate.DomainValidationOptions[*].ResourceRecord'

# Add the CNAME records to your hosted zone
# (repeat for each domain in the cert)
aws route53 change-resource-record-sets --hosted-zone-id ZXXXXXXXXX --change-batch '{
  "Changes": [{"Action":"CREATE","ResourceRecordSet":{
    "Name":"_xxx.example.com.","Type":"CNAME","TTL":300,
    "ResourceRecords":[{"Value":"_yyy.acm-validations.aws."}]
  }}]
}'
```

Wait for the cert to reach ISSUED status (typically 2-10 minutes with correct DNS):

```sh
aws acm wait certificate-validated --certificate-arn ARN --region us-east-1
```

#### 6. Set up nginx on VPS

Install nginx and configure it as a reverse proxy from port 80 to your app:

```sh
sudo apt-get install -y nginx

# Create site config
sudo tee /etc/nginx/sites-available/myapp > /dev/null << 'EOF'
server {
    listen 80;
    server_name origin.example.com example.com www.example.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/myapp /etc/nginx/sites-enabled/myapp
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

Open ports 80 and 443 in your firewall:

```sh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

Verify nginx works: `curl -s -o /dev/null -w '%{http_code}' http://YOUR_VPS_IP/` should return your app's response code.

#### 7. Import existing AWS resources into the Pulumi state (first deploy only)

Pre-flight created the hosted zone and ACM certificate outside Pulumi. Importing them tells Pulumi "manage these existing resources" so the first `pulumi up` reconciles against the current state instead of recreating duplicates.

Concrete import arguments with resolved provider IDs live in
`<render-output>/infra/import-plan.md`. The plan is render-output local and
idempotent under re-render — read it before running any import here.

A sample shape (for reference; use the resolved values from the import plan):

```sh
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- import \
  aws:route53/zone:Zone hosted_zone ZXXXXXXXXX
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- import \
  aws:acm/certificate:Certificate cert \
  arn:aws:acm:us-east-1:ACCOUNT:certificate/UUID
```

**Discipline:** mark imported resources with `protect=True` in the Pulumi infra
module so an accidental `pulumi destroy` cannot delete the hosted zone or
certificate, and apply `pulumi state protect --stack <stack> <urn>` to existing
state entries that were imported in earlier sessions.

When an environment has distribution publishing configured, that environment
stack also owns four non-secret repository variables: its public base URL,
bucket, CloudFront distribution ID, and exact origin ID. For a repository that
hosts a different product than the deploy-owner project, set
`distribution.repository_variable_namespace` explicitly to the product prefix
consumed by its release workflow; the renderer never guesses this cross-project
authority from the deploy namespace. For a repository that
already has those variables, generate a Pulumi preview import file for the
environment stack and adopt the four
`github:index/actionsVariable:ActionsVariable` records before the first apply;
preserve each generated parent and provider reference and use the provider ID
`<repository-name>:<variable-name>`. A clean post-import preview must show no
replacement or deletion. Do not leave these release inputs as manually managed
repository settings.

#### 8. Pulumi up

Apply each live stack through the Yoke-owned deploy flow when available. For
operator-attended runs, preview and apply through the same capability-owned
boundary:

```sh
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- preview
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- up --yes --non-interactive
yoke pulumi exec --project {{project_name}} --stack {{pulumi_vps_stack_name}} -- preview
yoke pulumi exec --project {{project_name}} --stack {{pulumi_vps_stack_name}} -- up --yes --non-interactive
yoke pulumi exec --project {{project_name}} --stack {{project_name}}-prod -- preview
yoke pulumi exec --project {{project_name}} --stack {{project_name}}-prod -- up --yes --non-interactive
```

Apply takes 3-5 minutes for legacy infra stacks; environment stacks can take
longer because Aurora, ACM validation, CloudFront, and DNS converge while the
origin EC2 box remains owned by the separately applied standalone VPS stack and
is resolved through a StackReference. If an environment apply partially
succeeds, keep the same stack state, fix config/template drift, run
`yoke pulumi exec --project {{project_name}} --stack <stack> -- preview`, and
rerun the corresponding `-- up --yes --non-interactive` command.

#### 9. Verify all 4 URL variants

```sh
curl -s -o /dev/null -w '%{http_code} %{redirect_url}' http://example.com/
# Expected: 301 https://example.com/

curl -s -o /dev/null -w '%{http_code}' https://example.com/
# Expected: your app's response (200 or 307 redirect to /login)

curl -s -o /dev/null -w '%{http_code} %{redirect_url}' http://www.example.com/
# Expected: 301 https://www.example.com/

curl -s -o /dev/null -w '%{http_code} %{redirect_url}' https://www.example.com/
# Expected: 301 https://example.com/
```

### Subsequent Deploys

After the first-time setup, updates only need capability-owned preview/apply
against each live
stack. Leave rendered-only stacks untouched until their activation ticket:

```sh
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- preview
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- up --yes --non-interactive
yoke pulumi exec --project {{project_name}} --stack {{pulumi_vps_stack_name}} -- preview
yoke pulumi exec --project {{project_name}} --stack {{pulumi_vps_stack_name}} -- up --yes --non-interactive
yoke pulumi exec --project {{project_name}} --stack {{project_name}}-prod -- preview
yoke pulumi exec --project {{project_name}} --stack {{project_name}}-prod -- up --yes --non-interactive
```

### Teardown

To remove the Pulumi-managed resources (CloudFront distribution, DNS alias records, CloudFront Function, EC2 instance, Elastic IP, security group):

```sh
yoke pulumi exec --project {{project_name}} --stack {{pulumi_vps_stack_name}} -- destroy --yes --non-interactive
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- destroy --yes --non-interactive
```

For environment stacks, destroy is a recovery operation, not a routine deploy
step: capture a managed backup or logical dump first, confirm the target env is
not render-only, then follow `ops/RECOVERY.md`.

This does **not** delete the hosted zone, ACM certificate, or origin DNS record (since they were created in the pre-flight step and protected with `protect=True` on the imported Pulumi resources). Delete those manually if needed:

```sh
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- state unprotect <urn>
yoke pulumi exec --project {{project_name}} --stack {{pulumi_infra_stack_name}} -- destroy --target <urn> --yes --non-interactive
```

**Note:** CloudFront distribution deletion can take several minutes. If destroy reports the resource as still deleting, the operation continues asynchronously — re-run `yoke pulumi exec --project {{project_name}} --stack <stack> -- refresh` later to reconcile.
