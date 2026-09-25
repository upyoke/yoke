# GitHub App CI Custody

This document owns the machine-enforced boundary that keeps GitHub App private
keys outside GitHub Actions.

## Runner-Fleet Token Broker

Operator-attended infrastructure previews and applies use the declared local
AWS and GitHub App authorities. The registry stack owns its non-secret
`YOKE_DELIVERY_CI_ROLE_ARN` workflow variable; manual edits to it are drift.
The retired GitHub Actions infrastructure preview lane has no OIDC role or
repository variable in the current registry Pack.

The client bounds Lambda responses and refuses function errors, invalid
payloads, expired grants, and a different repository binding. Error reporting
never includes a broker body or token.

The tenant API and generic function-call dispatcher are intentionally not token
brokers: their results can be ledgered or emitted as telemetry, and the tenant
does not own the operator App key. In GitHub Actions, AWS broker use is
mandatory and `aws_capability_env` selects authenticated OIDC credentials
before any machine-config or capability-store lookup. Missing broker or OIDC
authority fails closed; CI cannot select the local PEM path. Local operator
runs retain direct Secrets Manager access for source-development
administration.

## AWS Boundary

The registry stack owns one GitHub OIDC role:

- delivery: Platform `main` and `stage` only, action/resource-scoped delivery
  permissions, with an explicit App-key secret deny.

It also owns `YOKE_DELIVERY_CI_ROLE_ARN` as a GitHub Actions variable wired
directly to that role output. The first local operator apply creates it; no
manual ARN copy is part of steady state. Remove consumers of
`YOKE_INFRA_CI_ROLE_ARN` before applying the current Pack, which deletes that
retired variable and IAM role.

Pull requests, feature branches, and tags are not trusted. The deny covers
every configured App-key ARN plus the account's
`*github-app-private-key-*` name pattern, so it overrides any broader allow.

Each origin instance role alone may read its exact environment App-key ARN and,
when declared, decrypt it with one exact KMS key ARN. Deployment fetches a
pending file owned by the deploy user and a dedicated secrets group, grants
only that numeric supplemental group to the non-root core container, verifies
the key inside the pulled image, and promotes it atomically only after success.
A failed rotation deletes pending and keeps the prior durable key. The PEM
never crosses GitHub Actions, SSH stdin, Pulumi state, the control-plane
database, or the hosted broker response.

The delivery allow matrix is limited to:

- ECR login and image read/write for `<deploy_namespace>-*` repositories;
- EC2 describe plus start on instances tagged for the deploy namespace;
- RDS cluster discovery and reads only of RDS-owned secrets whose
  `aws:rds:primaryDBClusterArn` tag matches the deploy namespace;
- read-only `.pulumi` state objects and KMS decrypt on the configured state key;
- exact distribution buckets, read-only CloudFront distribution discovery, and
  CloudFront invalidation.

SSH uses DB-declared hosts and keys, and SSM is not part of these delivery
executors, so neither requires an AWS permission in the delivery role.
