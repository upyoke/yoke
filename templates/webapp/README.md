# Webapp Template

Full-stack web application scaffold: FastAPI + Next.js + app-local SQLite + Docker.

A reusable starting point for new Yoke-managed web applications.

## Database Boundary

The SQLite database in this template is the generated app's own database. It
is intentionally app-local (`APP_DB_PATH`, normally `app/data/app.db`) and is
validated with a worktree-local SQLite rehearsal surface. It is not Yoke's
control-plane database.

Yoke backlog state, claims, deployment flows, and project metadata live in
Yoke's Postgres control plane and are accessed through Yoke commands or the
registered function surface. Do not point Yoke operations at the generated
app database or at a `data/yoke.db` path inside a project worktree.

## Template Variables

All placeholder values use `{{VARIABLE_NAME}}` syntax and must be replaced during instantiation.

| Variable | Description | Example | Default |
|----------|-------------|---------|---------|
| `{{project_name}}` | Lowercase project identifier (no spaces, used in code, Docker, file paths) | `acme` | -- |
| `{{project_display_name}}` | Human-readable name (used in UI, docs, log messages) | `Acme Dashboard` | -- |
| `{{project_description}}` | One-line description of the project | `Client reporting dashboard` | -- |
| `{{api_port}}` | Port the FastAPI backend listens on | `8000` | `8000` |
| `{{web_port}}` | Port exposed for the Next.js frontend | `3000` | `3000` |
| `{{domain_name}}` | Apex domain for infrastructure (e.g., `example.com`) | `acme.com` | -- |
| `{{origin_host}}` | VPS hostname that CloudFront proxies to (must be a domain, not IP) | `origin.example.com` | -- |

## Instantiation Steps

### Step 1: Copy the scaffold

```bash
yoke templates fetch webapp --dest ~/path/to/webapp-template
cp -R ~/path/to/webapp-template/scaffold ~/path/to/new-project
cd ~/path/to/new-project
```

### Step 2: Replace template variables

Use find-and-replace across all files. Order matters -- replace `project_display_name` before `project_name` to avoid partial matches.

```bash
# Replace in order: longest variable names first
find . -type f -not -path './.git/*' -not -path '*/node_modules/*' \
  -exec sed 's/{{project_display_name}}/Acme Dashboard/g' {} + \
  -exec sed 's/{{project_description}}/Client reporting dashboard/g' {} + \
  -exec sed 's/{{project_name}}/acme/g' {} + \
  -exec sed 's/{{api_port}}/8000/g' {} + \
  -exec sed 's/{{web_port}}/3000/g' {} +
```

On macOS (BSD sed), use a temp-file approach instead:

```bash
for var_pair in \
  "{{project_display_name}}|Acme Dashboard" \
  "{{project_description}}|Client reporting dashboard" \
  "{{project_name}}|acme" \
  "{{api_port}}|8000" \
  "{{web_port}}|3000"; do
  placeholder="${var_pair%%|*}"
  value="${var_pair#*|}"
  find . -type f -not -path './.git/*' -not -path '*/node_modules/*' | while read f; do
    if grep -q "$placeholder" "$f" 2>/dev/null; then
      sed "s|$placeholder|$value|g" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    fi
  done
done
```

### Step 3: Initialize git

```bash
git init
git add -A
git commit -m "Initial scaffold from Yoke webapp template"
```

Publish the folder through Yoke's connected GitHub App:

```bash
yoke onboard
```

Choose **Existing folder on my machine**, select this folder, then choose
**Yes — publish to GitHub**. Yoke creates the repository, pushes through the
short-lived App user authorization, and keeps the stored git remote
credential-free.

### Step 4: Install backend dependencies

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 5: Install frontend dependencies

```bash
cd app/web
npm install
```

### Step 6: Set up environment

```bash
# From project root
cp .env.example .env
# Edit .env with your values:
#   APP_SECRET_KEY=<generate a random string>
#   ANTHROPIC_API_KEY=<optional, for LLM features>
```

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Step 7: Initialize the database

```bash
cd app
python3 db/init_db.py
```

This creates `data/app.db` with WAL mode enabled and the base schema (orgs, users, org_members, sessions).
Run `python3 db/migrations/migrate.py` to create the `schema_version` tracking table and apply Python migration modules under `app/db/migrations/`.

### Step 8: Seed the admin user

```bash
cd app
APP_ADMIN_PASSWORD=changeme python3 db/seed_users.py
```

This creates:
- **Default org:** `Default` (slug: `default`)
- **Superadmin user:** `admin@<project_name>.local` / `changeme`
- **Org membership:** Owner role in Default org

**Default credentials (local development only):**

| Field | Value |
|-------|-------|
| Email | `admin@<project_name>.local` |
| Password | `changeme` |
| Role | `superadmin` |

Change these immediately in any non-local environment.

### Step 9: Register the project in Yoke

After instantiation, register or import the project so Yoke can manage it.
Use the product CLI and let the generated project onboarding handoff finish
project-specific policy and capability setup:

```bash
yoke project create ~/path/to/acme \
  --slug acme \
  --name "Acme Dashboard" \
  --github-repo your-org/acme \
  --default-branch main \
  --public-item-prefix ACM \
  --config ~/.yoke/config.json \
  --dry-run
```

### Step 10: Populate project settings

Store project-specific runtime, provider, and deploy values in Yoke's DB-backed
project settings and capabilities. Use the onboarding checklist and product CLI
capability surfaces rather than writing provider credentials into repo files:

```bash
yoke projects capability has --project acme --cap-type aws-admin --json
yoke projects capability-secret set --project acme --cap-type aws-admin --key access_key_id --value-stdin
yoke projects capability-secret set --project acme --cap-type aws-admin --key secret_access_key --value-stdin
yoke project-structure patch apply --project acme --ops-json '<json-ops>'
```

Fill in real values as they become available (e.g., after creating an AWS
account, domain, and VPS). Domain, CDN, Pulumi, and environment values live in
DB site/environment settings and project capabilities, not repo files.

### Step 11: Generate ops artifacts

Preview the managed deployment references, workflows, ops programs, and static
infrastructure rendered from the active packaged template plus the project's
DB-backed settings. Project-authored deployment help stays in the project's
own `.yoke/runbooks/`; generic rendered references use the distinct
`docs/yoke-generated/deployment-reference/` namespace:

```bash
yoke project artifacts refresh ~/work/my-service --project my-service
yoke project artifacts refresh ~/work/my-service --project my-service --apply
yoke project artifacts refresh ~/work/my-service --project my-service --verify
```

Preview is the default and lists exact creates, updates, prunes, and conflicts.
Apply starts only after full path, symlink, manifest, and ownership preflight;
project-authored deviations are preserved as refusing conflicts. Planning also
requires the checkout's installed project id to match the server bundle; when
the project has a verified repository binding, its live Git origin must also
match. Local/offline projects can operate without that optional repository
binding. The manifest at `.yoke/artifact-manifest.json` records template
version plus template, settings, and rendered-content digests. `--verify` is
the CI/external-project drift gate. The source-dev template-tree override is an
org-admin-only diagnostic and never bypasses checkout identity. This is
distinct from `yoke project refresh`, which updates only the managed Yoke
operating substrate.

The fetched template includes:
- `ops/DEPLOY.md` -- operator runbook
- `ops/deploy.yml` -- production deploy workflow source
- `ops/hotfix.yml` -- hotfix deploy workflow source (manual trigger only)
- `ops/smoke.yml` -- smoke test workflow source
- `ops/ephemeral-deploy.yml` -- ephemeral environments
- `ops/ephemeral-teardown.yml` -- ephemeral teardown
- `scaffold/docker-compose.yml` -- Docker Compose config
- `scaffold/app/Dockerfile` -- API Dockerfile
- `scaffold/app/entrypoint.sh` -- API entrypoint template
- `scaffold/app/web/Dockerfile` -- Web Dockerfile
- `scaffold/app/web/next.config.ts` -- Next.js config

Values are pulled from DB-backed project, site, environment, and capability
settings by the project onboarding flow. Fields not yet configured show as
`TODO` until onboarding records the real values.

For raw, unrendered template inspection only, fetch specific source groups:

```bash
yoke templates fetch webapp --dest scratch/webapp-template --only ops/ --force
yoke templates fetch webapp --dest scratch/webapp-template --only scaffold/ --force
```

**Shell output files are generated artifacts.** Template source files carry a
`.sh.tmpl` extension. Project onboarding or project-local setup materializes the
needed executable files in the managed project workspace before deployment.

Pulumi stack YAML is deliberately outside generic artifact reconciliation
because it carries stack-scoped secrets-provider/operator-state lines. Use
`yoke projects pulumi-stack-config get` or `yoke pulumi exec` for an exact
declared stack; the generic operation owns only static Pulumi program sources.

The hotfix workflow template is identical to the deploy workflow except: it uses `workflow_dispatch` only (no `push: [main]` trigger) and is named `{{project_display_name}} Hotfix`. It is rendered as `{project}-hotfix.yml` alongside the other workflows.

### Step 12: Bootstrap GitHub Actions

Once your VPS, SSH keys, and GitHub App connection are configured:

```bash
yoke onboard project ~/path/to/acme \
  --slug acme \
  --name "Acme Dashboard" \
  --github-repo your-org/acme \
  --default-branch main \
  --public-item-prefix ACM \
  --config ~/.yoke/config.json \
  --dry-run
```

This handles:
- Preflight validation (9 checks with actionable fix instructions)
- GitHub Secrets creation (`ACME_SSH_KEY`, `ACME_SSH_HOST`, `ACME_SSH_USER`)
- Production environment with optional reviewer protection
- Workflow file generation and commit to the project's main branch
- Post-setup verification

Run `--preflight-only` first to check readiness without making changes:

```bash
yoke onboard checklist --run-id <run-id>
```

The optional runner fleet requires an explicit privileged GitHub repository
binding and App authority plus `administration: write`,
`repository_hooks: write`, and `actions_variables: write`. This may be a
dedicated operator-only App so the product App stays least-privileged. Its
short-lived token, digested authority
envelope, ingress ordering, existing-variable adoption, fail-safe routing, and
stable `runnerFleetRoutingVariable` ownership are specified in
[RUNNER-FLEET.md](RUNNER-FLEET.md); direct variable writes are drift.

### Step 13: Docker build and run

```bash
# From project root
docker compose build
docker compose up -d
```

The API is available at `http://localhost:<api_port>` and the web dashboard at `http://localhost:<web_port>`.

To verify:

```bash
curl http://localhost:8000/api/health
# Should return: {"status":"ok","data":{"version":"0.1.0","db_ok":true,"schema_version":0}}
```


## Infrastructure Setup

Pulumi quick start (the full first-time sequence is in [SETUP.md](SETUP.md) →
[SETUP-DEPLOYMENT.md](SETUP-DEPLOYMENT.md)):

```sh
# Bootstrap S3 state bucket + KMS key once per AWS account, then point
# Pulumi at them and create each non-render-only project stack.
pulumi login s3://{{state_bucket}}?region={{aws_region}}
pulumi stack init {{pulumi_infra_stack_name}} \
  --secrets-provider awskms://{{kms_key_alias}}?region={{aws_region}}
pulumi stack init {{pulumi_vps_stack_name}} \
  --secrets-provider awskms://{{kms_key_alias}}?region={{aws_region}}
pulumi stack init {{project_name}}-prod \
  --secrets-provider awskms://{{kms_key_alias}}?region={{aws_region}}
pulumi up --stack {{pulumi_infra_stack_name}}
pulumi up --stack {{pulumi_vps_stack_name}}
pulumi up --stack {{project_name}}-prod
```

For full AWS, Pulumi, CloudFront, and nginx deployment setup, see
[SETUP.md](SETUP.md).

### Project stacks and environment instances

The template defines legacy single-purpose stack types and newer environment
stack instances. A project declares legacy stacks in
`sites.settings.pulumi.stacks` (absent = the default `["infra", "vps"]`
full-webapp pair), and declares composed env stacks under
`sites.settings.pulumi.stackInstances`:

- **infra** — CloudFront + ACM (import-only) + Route 53 alias records. Imports
  an existing hosted zone by id; never creates one. If the project has no
  domain stack, this stack also owns `domains[].txt_records` and
  `domains[].mx_records`.
- **vps** — EC2 + Elastic IP + security group.
- **domain** — creates the Route 53 hosted zone and (optionally) manages the
  domain registration. A DNS-only project declares just `["domain"]` and gets
  no EC2/CloudFront surface. When present, this stack owns
  `domains[].txt_records` and `domains[].mx_records`.
- **environment instance** — renders `Pulumi.<instance>.yaml` from
  `Pulumi.environment-stack.yaml.tmpl` and composes database, VPS/origin, and
  API edge resources for one env. The env stack discovers the account's default
  VPC/subnets during Pulumi execution; operators do not copy subnet ids into
  template docs. Set `renderOnly: true` for envs that should be generated for
  review but not initialized or applied yet.

The split keeps responsibilities clean: the **template** owns the capability
shape (the stack code), the DB owns project-specific **values** (domain, account,
region, state bucket, which stacks), and **secrets never live in tracked
template files** — AWS credentials come from the project's `aws-admin`
capability, and Pulumi config secrets are encrypted into the per-stack YAML via
the KMS secrets provider.

## Development Reference

For included packages, CI/CD workflow topology, adding components, and
enforcement details, see [DEVELOPMENT.md](DEVELOPMENT.md).
