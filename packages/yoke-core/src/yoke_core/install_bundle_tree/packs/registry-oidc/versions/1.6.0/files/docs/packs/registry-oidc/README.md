# Registry and OIDC Pack

Provides a container registry and a GitHub Actions delivery role using
short-lived OIDC tokens. Infrastructure preview and apply use operator-held
AWS authority outside GitHub Actions.

## Project-specific work

- Set the repository, registry name, AWS account, regions, branches, and GitHub
  environments.
- Narrow trust conditions and permissions to the project's real workflows.
- Apply the stack, then verify `YOKE_DELIVERY_CI_ROLE_ARN` matches the delivery
  role output before removing any static delivery credentials.
- Prove delivery assumptions in a live workflow. Preview infrastructure from
  a connected local operator using the project's declared AWS authority.

The delivery role is the only GitHub Actions role output. Upgrading this Pack
removes the old infrastructure preview role and its
`YOKE_INFRA_CI_ROLE_ARN` repository variable. Remove workflows that consume
the variable before applying the new Pack version; the apply will delete the
old IAM role and variable from the stack.

## Optional delivery authority

The delivery role can additionally be allowed to run named SSM documents on
tag-selected instances and to move build artifacts under named S3 key
prefixes. It is off unless a project asks for it, and a project that never
asks keeps exactly the policy it had before this existed.

State it per environment, under `delivery_authority` in that environment's
settings. Every field bounds the next one, and all four travel together:

| Field | Bounds |
|---|---|
| `instance_tags` | which instances `ssm:SendCommand` may target |
| `documents` | which SSM documents may be run on them |
| `artifact_buckets` | the buckets artifacts move through |
| `artifact_key_prefixes` | which keys in those buckets may be read or written |

A role that can run a command on an instance can run anything that instance's
own role permits, so the grant is deliberately narrow and deliberately
fail-closed:

- Stating documents without `instance_tags` is refused — a document with no
  instance selector would be runnable on every instance in the account.
- Stating `instance_tags` without documents is refused — a selector with no
  named document would allow any document to be run.
- Stating `artifact_buckets` without prefixes is refused — a whole bucket is
  never the intended scope.
- An unknown key is refused rather than ignored, because a misspelled bound is
  a bound that silently does not apply.

One delivery role serves every environment of a project, so the rendered grant
is the union of what each environment stated. That union is lossless in both
directions: environments naming different buckets contribute all of them, and
environments naming the same tag key with different values yield one selector
matching any of those values. A project whose stage and production origins
carry different `Name` tags, or whose environments keep separate artifact
buckets, therefore gets one role that reaches both and nothing else.

Several tag keys still have to match together, so a project that tags its
delivery targets by role can keep stating a compound selector such as
`{project: acme, role: origin}` and reach exactly those instances.

The instance condition uses `ssm:resourceTag/`, the service-specific key
Systems Manager's own Run Command guidance uses to bound `SendCommand` to
tagged nodes. The whole grant rests on that condition matching — a condition
that never matches denies every delivery — so it follows the documented key
rather than the global `aws:ResourceTag` one.

The grant covers the whole sequence a delivery performs, not just the send:
finding the target, running the document, and reading the result back. The
target lookup needs `ssm:DescribeInstanceInformation`, which confirms the
instance is a managed node with an online agent before a command is fired at
it. Systems Manager defines no resource type for that action, so unlike
`SendCommand` it cannot be narrowed by tag or ARN — opting into this grant
means accepting an account-wide inventory read that cannot be scoped down. It
is included because a grant that cannot resolve its own target cannot perform
the delivery it exists for.

A document is granted by the ARN Systems Manager evaluates for it, and that
ARN carries the owner's account. An AWS-owned public document such as
`AWS-RunShellScript` is owned by no account, so it is evaluated as
`arn:aws:ssm:<region>::document/AWS-RunShellScript`, with the account field
empty; AWS reserves the `AWS-` prefix for its own documents, so a name with
that prefix is granted without an account and a customer-owned document is
granted with the project's. A grant that put the project's account into every
document ARN would read correctly and deny every send — the denial names the
resource the caller asked for, never the one the policy granted, so the empty
field never shows in the message that reports it.
