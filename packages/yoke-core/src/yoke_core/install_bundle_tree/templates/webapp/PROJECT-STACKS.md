# Project Stacks and Environment Instances

This reference describes the infrastructure stack model generated from the
webapp template.


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
