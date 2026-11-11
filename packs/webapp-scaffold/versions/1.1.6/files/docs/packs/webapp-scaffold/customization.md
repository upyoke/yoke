# Customizing the Webapp Scaffold Pack

Pack output is project-owned source. Customization is normal and does not need
a deviation manifest, central approval record, or continuing drift check.

## Safe ownership model

- Change, rename, or remove installed files as the project requires.
- Commit .yoke/packs.json so a later update can reconstruct the old baseline.
- Preview yoke packs update webapp-scaffold before applying it.
- Resolve overlapping update conflicts exactly like ordinary Git conflicts.
- Keep deleted upstream files when the project still needs them; Yoke never
  automatically prunes project-owned source.

If a customization would benefit many future projects, update the Pack source
and publish a new immutable version. Existing projects opt into that version;
they do not continuously synchronize with Yoke.

## Expected customization areas

### Application behavior

Replace the starter routes, dashboard, settings, copy, navigation, and data
model. Add domain routers under app/api/routers/, migrations under
app/db/migrations/, and project-specific web pages and stores under
app/web/src/.

### Authentication and authorization

The starter uses cookie sessions and a small role hierarchy. Decide password,
session, invitation, recovery, audit, SSO, and service-token requirements
before production use.

### Database

The starter database is app-local SQLite; it is unrelated to Yoke's Postgres
control plane. Keeping SQLite is valid for suitable applications. Moving to
Postgres requires adapting the application connection layer, schema,
migrations, tests, backup, and restore procedures; installing the
managed-database Pack supplies infrastructure composition, not that
application rewrite.

### Runtime

The scaffold itself does not own Docker files. Install container-runtime only
when that runtime fits the project, then customize its installed Compose,
Dockerfile, entrypoint, and nginx source normally.

### Delivery

The scaffold owns only its basic CI workflow. Production, smoke, preview
environment, host-maintenance, and runner workflows come from their respective
Packs and require project-specific infrastructure and runbook work.

## Update checklist

Before applying an update:

1. Commit or stash current project work.
2. Read the Pack's release notes and preview exact changes.
3. Review automatic merges and every explicit conflict.
4. Run both the Pack verification entrypoints and the project's own tests.
5. Commit the updated source and .yoke/packs.json together.
