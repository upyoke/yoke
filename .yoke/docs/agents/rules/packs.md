# Pack capabilities

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Packs
<!-- /yoke:breadcrumbs -->

## Packs

- Package reusable capabilities in `packs/<slug>/` with immutable versions. Publish changes
  as new versions; projects choose when to update.
- Installed Pack files belong to the project. `.yoke/packs.json` records the baseline for a
  three-way update (`yoke packs update --help`).
- An unreleased version installs with `--catalog commit:SHA`; served-catalog updates refuse
  with `pack-source-unreleased` until a release carries it.
- Config lives in DB settings (`project_capabilities`, `sites.settings`,
  `environments.settings`) or project `.yoke/` policy, not in the Pack.

## Credentials

Credentials belong to project capabilities; bare `aws ...` may fail. Use Yoke's capability
resolver for subprocess credentials. Verify keys or redacted evidence;
never print secrets.
Storage: [capabilities](../../projects/capabilities.md).

## Declared infrastructure

Declare external resources and settings in project IaC in the same change.
Import or remove anything created by hand during investigation; record which you did.
Emergency patches need operator approval and immediate IaC catch-up.
Put reusable infrastructure in Packs.

## Related

- [Deployment runs and packaged capabilities](delivery.md)
- [Release-time roles](release-roles.md)
