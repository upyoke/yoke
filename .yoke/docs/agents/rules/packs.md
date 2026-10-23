# Pack capabilities

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Packs
<!-- /yoke:breadcrumbs -->

## Packs

- Package a reusable capability as a Pack: `packs/<slug>/` with immutable versions. Improve
  the Pack and publish a new version; each project chooses when to update.
- Installed Pack files belong to the project. `.yoke/packs.json` records the baseline for a
  three-way update (`yoke packs update --help`).
- An unreleased version installs with `--catalog commit:SHA`; served-catalog updates refuse
  with `pack-source-unreleased` until a release carries it.
- Config lives in DB settings (`project_capabilities`, `sites.settings`,
  `environments.settings`) or project `.yoke/` policy, not in the Pack.

## Credentials

Provider credentials belong to project capabilities; bare `aws ...` may fail. Pass credentials
to subprocesses through the Yoke capability resolver. Verify keys or redacted evidence;
never print secrets.
Storage: [capabilities](../../projects/capabilities.md).

## Declared infrastructure

Declare external resources and settings in project infrastructure-as-code in the same change.
Import or remove anything created by hand during investigation; record which you did.
Emergency patches need operator approval and immediate IaC catch-up.
Reusable infrastructure belongs in a Pack.

## Related

- [Deployment runs and packaged capabilities](delivery.md)
- [Release-time roles](release-roles.md)
