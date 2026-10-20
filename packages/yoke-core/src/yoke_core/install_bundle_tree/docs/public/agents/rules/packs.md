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

Provider credentials belong to a project capability, not the shell; a bare `aws ...` may fail
for that reason. Use the Yoke capability resolver to pass them to a subprocess. Verify by
listing keys or redacted evidence; never print a secret.
Storage: [capabilities](../../projects/capabilities.md).

## Declared infrastructure

Create or change an external resource only through the project's infrastructure-as-code
declaration, in the same change. A console or ad hoc CLI result is not a declaration: import it
or remove it. Reusable infrastructure belongs in a Pack.

## Related

- [Deployment runs and packaged capabilities](delivery.md)
- [Release-time roles](release-roles.md)
