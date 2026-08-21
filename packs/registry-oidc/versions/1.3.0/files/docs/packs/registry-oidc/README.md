# Registry and OIDC Pack

Provides a container registry and separate GitHub Actions roles for
infrastructure changes and application delivery using short-lived OIDC tokens.

## Project-specific work

- Set the repository, registry name, AWS account, regions, branches, and GitHub
  environments.
- Narrow trust conditions and permissions to the project's real workflows.
- Apply the stack, then verify the published repository variables match its
  role outputs before removing any static credentials.
- Prove both infrastructure and delivery assumptions in live workflows.
- GitHub's built-in workflow token cannot read repository variables. A hosted
  Actions preview therefore needs a project-configured, repository-scoped App
  token broker; the Self-hosted Runners Pack provides one when that Pack is
  installed. Projects without that Pack can run the preview from a connected
  local operator or provide an equivalent broker before enabling the CI lane.

The infrastructure and delivery role outputs are the only supported GitHub
Actions role outputs. Projects upgrading from an earlier version may remove
the combined compatibility output after both repository variables and both
workflow paths have been proven.

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
