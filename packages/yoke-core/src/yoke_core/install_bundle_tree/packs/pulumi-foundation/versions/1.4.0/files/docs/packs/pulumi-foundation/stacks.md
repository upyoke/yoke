# Pulumi Stack Composition

The Pulumi Foundation Pack supplies composition mechanics; component Packs
supply independently useful infrastructure behavior.

## Stack sources

- pulumi-foundation: project entrypoint, configuration helpers, aliases, and
  GitHub repository provider.
- webapp-environment-infrastructure: composition of a deployable environment
  from the VPS, database, registry, API edge, and supporting policies.
- vps-hosting: standalone VPS component.
- domain-cdn-edge: hosted zone, DNS, API edge, certificate, and CDN components.
- registry-oidc: container registry and GitHub Actions federation.
- managed-database: managed Postgres component.
- self-hosted-runners: runner fleet and token-broker components.

Installing pulumi-foundation alone creates no cloud resources.

## Stack types and environment instances

A project may declare standalone component stacks or composed environment
instances. Environment instances select components through explicit project
settings and render one exact stack configuration at execution time. Keep
render-only instances inactive until reviewed.

## Authority split

- Pack-installed infra/ files define reusable program behavior.
- The project's DB settings define its stack selection and non-secret values.
- Capability secret stores hold provider credentials.
- Per-stack operator state holds the initialized backend and secrets-provider
  metadata.
- Pulumi checkpoints describe live resource state.

No layer should impersonate another. In particular, Pack receipts do not store
stack state or secrets, and customized project infrastructure source is not
central drift.

## Updating

Preview and apply one component Pack update at a time, review the merged source,
then run exact-stack Pulumi previews for every affected project stack. A Pack
update is not an infrastructure apply.
