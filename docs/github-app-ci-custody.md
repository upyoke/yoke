# GitHub App CI Custody

This document owns the machine-enforced boundary that keeps GitHub App private
keys outside GitHub Actions.

## Runner-Fleet Token Broker

Infrastructure CI uses a dedicated `infrastructure_ci` actor and run-scoped
HTTPS connection. `yoke runner-fleet exec` posts the canonical renderer-
authority digest to
`POST /v1/projects/<project>/runner-fleet-token`. The route requires
`runner_fleet.token.issue`, rebuilds the digest from current DB authority, and
returns only a short-lived installation token scoped to the bound repository
with `repository_hooks:read` and `actions_variables:read`. Local
operator-attended applies mint a separate process-only token with write scope;
CI can refresh/preview GitHub resources but cannot mutate them. The registry
stack uses the same boundary to own its two non-secret workflow role-routing
variables; manual repository-variable edits are drift.

Responses are `Cache-Control: no-store`; clients refuse redirects, cacheable
responses, a different repository binding, and response bodies that do not
match the typed contract. Error reporting never includes a broker body.

The generic function-call dispatcher is intentionally not used because its
results are ledgered and emitted as telemetry. In GitHub Actions, broker use is
mandatory and `aws_capability_env` selects authenticated OIDC credentials
before any machine-config or capability-store lookup. Missing broker or OIDC
authority fails closed; CI cannot select the local PEM path. Local operator
runs retain direct Secrets Manager access for source-development
administration.

## AWS Boundary

The registry stack owns two exact-branch GitHub OIDC roles:

- infrastructure: Platform `main` only, Pulumi preview authority only
  (`ViewOnlyAccess` plus exact state reads), with explicit
  secret-value and privilege-escalation denies;
- delivery: Platform `main` and `stage` only, action/resource-scoped delivery
  permissions, plus the same explicit deny.

It also owns `YOKE_INFRA_CI_ROLE_ARN` and `YOKE_DELIVERY_CI_ROLE_ARN` as
GitHub Actions variables wired directly to those role outputs. The first local
operator apply creates them; no manual ARN copy is part of steady state.

Pull requests, feature branches, tags, and GitHub-environment subjects are not
trusted. The deny covers every configured App-key ARN plus the account's
`*github-app-private-key-*` name pattern, so it overrides any broader allow.

Each origin instance role alone may read its exact environment App-key ARN and,
when declared, decrypt it with one exact KMS key ARN. Deployment fetches a
pending owner-only file, verifies it inside the pulled core image, and promotes
it atomically only after success; a failed rotation deletes pending and keeps
the prior durable key. The PEM never crosses GitHub Actions, SSH stdin, Pulumi
state, the control-plane database, or the hosted broker response.

The delivery allow matrix is limited to:

- ECR login and image read/write for `<deploy_namespace>-*` repositories;
- EC2 describe plus start on instances tagged for the deploy namespace;
- RDS cluster discovery and reads only of RDS-owned secrets whose
  `aws:rds:primaryDBClusterArn` tag matches the deploy namespace;
- read-only `.pulumi` state objects and KMS decrypt on the configured state key;
- exact distribution buckets and CloudFront invalidation.

SSH uses DB-declared hosts and keys, and SSM is not part of these delivery
executors, so neither requires an AWS permission in the delivery role.
