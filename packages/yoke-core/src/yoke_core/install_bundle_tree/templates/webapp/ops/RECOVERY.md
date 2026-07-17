# {{project_display_name}} — Recovery Runbook

If the EC2 instance is unrecoverable (corrupted root volume, accidentally
terminated outside Pulumi, etc.) and the VPS stack needs to be rebuilt from
scratch, follow this sequence. The biggest single risk is **data loss in the
`{{project_name}}-data` Docker volume** (database file + any operator-uploaded
artifacts), which lives on the EC2 root EBS and is NOT backed up by anything
automated today.

This runbook is intentionally separate from `DEPLOY.md` — that file covers
routine deploy/teardown; this one covers the irregular case. For projects using
environment stack instances, recover the managed data plane first; for legacy
VPS-only projects, skip to the root-volume rebuild sequence below.

## Environment stack recovery first rules

- Do not run `pulumi destroy` against an environment stack until a managed
  backup or logical dump is recorded and the operator has confirmed the target.
- If `webapp-infra:render_only: "true"` is present, the stack is documentation
  only; do not initialize, apply, or recover it as a live env.
- Keep raw `psql`, `pg_dump`, AWS, and Pulumi captures in `/tmp` or another
  scratch path. Commit only redacted outcomes.
- Fix renderer-owned DB site/environment settings or project capability
  settings, re-render, then rerun Pulumi.

## Partial Pulumi apply

Environment stacks intentionally converge several resource families in one
state file. A failed first apply can leave live EC2, RDS, ACM, DNS, or
CloudFront resources in state. Do not delete them by hand.

```sh
pulumi --cwd <render-output>/infra stack select <env-stack>
pulumi --cwd <render-output>/infra stack --show-urns
pulumi --cwd <render-output>/infra refresh --stack <env-stack>
pulumi --cwd <render-output>/infra preview --stack <env-stack>
pulumi --cwd <render-output>/infra up --stack <env-stack> --yes
```

If the failure is missing operator-owned input such as an EC2 key pair, create
  the missing input in the same region, record it in DB site/environment settings
  or project capabilities, re-render, then rerun `preview` and `up` against the
  same stack.

## Managed Postgres access and backup

Use the stack outputs as the source of truth for the database endpoint, secret
ARN, origin host/EIP, and security groups. Access is through an operator SSH
tunnel to the sibling origin, not through the application runtime:

```sh
aws secretsmanager get-secret-value --secret-id <databaseSecretArn> \
  --query SecretString --output text > /tmp/{{project_name}}-db-secret.json
ssh -N -L <local-port>:<databaseClusterEndpoint>:5432 {{ssh_user}}@<origin-host>
PGPASSWORD=<redacted> psql -h 127.0.0.1 -p <local-port> \
  -U <secret-username> -d <database-name>
```

Before risky changes, capture provider metadata and, when needed, a logical
dump into scratch storage:

```sh
aws rds describe-db-clusters --db-cluster-identifier <cluster-id>
PGPASSWORD=<redacted> pg_dump -h 127.0.0.1 -p <local-port> \
  -U <secret-username> -d <database-name> --no-owner --no-privileges \
  --file=/tmp/{{project_name}}-proof.sql
```

For a restore rehearsal, restore into a scratch schema or scratch database,
verify row counts/checksums, then drop the scratch target before recording the
redacted result.

## DNS/TLS/API edge recovery

Environment stacks create API DNS records and ACM validation records against an
existing hosted zone. If validation stalls or API DNS fails:

```sh
aws route53 list-resource-record-sets --hosted-zone-id <zone-id>
aws acm describe-certificate --certificate-arn <api-certificate-arn> \
  --region us-east-1
aws cloudfront get-distribution --id <distribution-id>
```

Confirm there is one hosted zone for the domain, the certificate is in
`ISSUED`, CloudFront is `Deployed`, and the API alias points at the rendered
distribution. Correct config, rerender, and rerun `pulumi preview` before `up`.

## Secret exposure

If a credential, secret JSON, private key, or database URI reaches a tracked
file or shared log, stop recovery work. Remove the artifact from the branch,
rotate the affected AWS/IAM/RDS/Secrets Manager material through the provider
console or CLI, invalidate local scratch copies, and record only the redacted
rotation outcome.

## 0. Capture rollback context

Snapshot the current root volume **before** any destroy step. Cheap insurance —
gives you a fallback if anything goes wrong mid-rebuild.

```sh
AWS_PROFILE=default aws ec2 create-snapshot \
  --volume-id "$(aws ec2 describe-instances \
    --instance-ids <current-instance-id> \
    --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' \
    --output text)" \
  --description "{{project_name}}-vps pre-rebuild $(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Note the SnapshotId returned — needed for restore in step 4.
```

## 1. Preserve operator-managed state on local machine

The `.env` file on the VPS at `/home/{{ssh_user}}/{{project_name}}-app/.env` is
NOT in git (gitignored) and NOT in the deploy workflow. Pulumi doesn't know
about it. Pull a local copy before destroy:

```sh
scp {{ssh_user}}@{{origin_ip}}:/home/{{ssh_user}}/{{project_name}}-app/.env \
  ./{{project_name}}-prod-env-backup.env
```

Without this, the rebuilt instance comes up but the app can't auth, talk to
upstreams, or read its database connection settings.

## 2. Unprotect before destroy

Every resource imported via `pulumi import --protect` (CloudFront distribution,
CloudFront Function, ACM cert, hosted zone, Route 53 records, security group,
EC2 instance, EIP) carries the `protect` flag. `pulumi destroy` refuses to
delete protected resources. Unprotect each by URN first:

```sh
pulumi --cwd <render-output>/infra stack select {{pulumi_vps_stack_name}}
for urn in $(pulumi --cwd <render-output>/infra stack --show-urns \
  | grep ":aws:" | awk '{print $NF}'); do
  pulumi --cwd <render-output>/infra state unprotect "$urn" --yes
done
```

`--skip-protected` on destroy is also valid, but unprotect-then-destroy
surfaces the safety gate one resource at a time — easier to abort mid-sweep
if you change your mind.

## 3. Destroy + up the VPS stack

```sh
pulumi --cwd <render-output>/infra destroy --stack {{pulumi_vps_stack_name}} --yes
pulumi --cwd <render-output>/infra up --stack {{pulumi_vps_stack_name}} --yes
```

**Critical: the Elastic IP changes.** Pulumi allocates a fresh EIP on the new
`vpsElasticIp` resource. The old IP (`{{origin_ip}}` in the current config) is
released. This means:

- The Route 53 alias record managed by `{{pulumi_infra_stack_name}}` still
  points at CloudFront, so the customer-facing hostname is unaffected.
- The origin host A record (manually managed outside Pulumi) likely points at
  the OLD `{{origin_ip}}`. Update it via `aws route53 change-resource-record-sets`
  to the new EIP before traffic flows back.
- DB server/SSH settings may need an origin host/IP update if the value is
  referenced by ops scripts.
- The host key on the new instance is fresh — `ssh-keygen -R <old-eip>`
  locally to clear the stale entry before the first SSH-in.

## 4. Restore data from snapshot

The new EC2 has a fresh empty EBS root volume. Mount the pre-rebuild snapshot
as a secondary volume on the new instance, copy the `{{project_name}}-data`
Docker volume contents into place, then detach.

```sh
# A. Create a volume from the snapshot in the same AZ as the new instance.
NEW_INSTANCE_AZ=$(aws ec2 describe-instances --instance-ids <new-instance-id> \
  --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text)
RESTORE_VOL=$(aws ec2 create-volume \
  --snapshot-id <SnapshotId-from-step-0> \
  --availability-zone "$NEW_INSTANCE_AZ" \
  --volume-type gp3 \
  --query 'VolumeId' --output text)

# B. Attach as /dev/sdf to the new instance.
aws ec2 attach-volume --volume-id "$RESTORE_VOL" \
  --instance-id <new-instance-id> --device /dev/sdf

# C. On the new instance: mount, copy, unmount.
ssh {{ssh_user}}@<new-eip> 'sudo mkdir -p /mnt/restore && \
  sudo mount /dev/nvme1n1p1 /mnt/restore && \
  sudo cp -a /mnt/restore/var/lib/docker/volumes/{{project_name}}-app_{{project_name}}-data \
    /var/lib/docker/volumes/ && \
  sudo umount /mnt/restore'

# D. Detach + delete the restore volume.
aws ec2 detach-volume --volume-id "$RESTORE_VOL"
aws ec2 delete-volume --volume-id "$RESTORE_VOL"
```

The exact device name (`/dev/nvme1n1p1`) varies by instance type — `lsblk` on
the instance confirms what attached as `/dev/sdf`. ARM Graviton instances
typically show NVMe device names regardless of the requested `/dev/sd*`.

## 5. Re-run provisioning + redeploy

```sh
# Reinstall .env that step 1 preserved
scp ./{{project_name}}-prod-env-backup.env \
  {{ssh_user}}@<new-eip>:/home/{{ssh_user}}/{{project_name}}-app/.env

# Bootstrap base packages
ssh {{ssh_user}}@<new-eip> 'sudo sh /tmp/provision-ec2.sh'

# Re-issue TLS cert (watch Let's Encrypt rate limit: 5 dup certs/domain/week)
ssh {{ssh_user}}@<new-eip> 'sudo sh /tmp/provision-tls.sh'

# Reinstall cron jobs (build cache prune, weekly cleanup, ephemeral cleanup)
ssh {{ssh_user}}@<new-eip> 'sh /tmp/setup-vps-maintenance.sh'

# Redeploy application through the recovery item's configured Yoke flow.
# From a Yoke-enabled Codex session, run: /yoke usher YOK-N
```

Replace `YOK-N` with the recovery item. Usher resolves the project's bound
repository and dispatches the configured workflow with a short-lived GitHub
App installation token.

## 6. Verify

```sh
sh <render-output>/ops/verify-deployment.sh {{domain}} <new-eip>
```

CloudFront propagation after the EIP change is 15-30 min —
`verify-deployment.sh` may flake during that window. Re-run after the
distribution status returns to `Deployed`
(`aws cloudfront get-distribution --id <cf-id>`).

## Recovery testing

Practice this whole sequence on a parallel staging stack (e.g.
`staging-vps`) before doing it on prod. A bare-VPS staging stack (no
CloudFront, no TLS, no DNS) costs roughly $5/month while it runs and lets
you exercise destroy/up cycles without customer impact. The staging stack
does NOT need data restoration — it's there to validate the IaC plumbing,
not the data path.

A staging-vps validation in an isolated `/tmp` working directory proved the
destroy/up cycle on `s3://{{state_bucket}}` runs cleanly in roughly 30
seconds per direction, total cost under $0.01, with no orphan resources
left after teardown.

## What this recipe does NOT cover

- **Pulumi state corruption.** If `s3://{{state_bucket}}` itself is lost,
  recovery is `pulumi import` on every resource from a fresh stack — slow,
  but live AWS state is untouched, so doable. Keep the S3 bucket versioning
  ON so accidental state mutations can be rolled back.
- **Account-level breach or revocation.** Outside this runbook's scope.
- **Application-level data corruption.** This restores VPS infra + DB FILE,
  not DB CONTENT correctness. Application-level rollback is a separate
  runbook.
