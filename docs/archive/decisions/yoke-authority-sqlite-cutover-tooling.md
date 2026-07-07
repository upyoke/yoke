---
retired-without-apply: true
---

# Retire the one-time SQLite → Aurora authority cutover tooling

## Decision

Delete the operator-attended tooling that performed Yoke's one-time control-plane
authority cutover from an archived SQLite snapshot into Aurora (Postgres):

- `yoke_core.domain.yoke_authority_migration`
- `yoke_core.domain.yoke_authority_schema_copy`
- `yoke_core.domain.yoke_authority_verification`

and their tests
(`test_yoke_authority_migration`, `test_yoke_authority_migration_boundary`,
`test_yoke_authority_verification`).

## Why

The cutover is complete. Yoke's active control plane is Aurora Postgres; the
authoritative DB is `yoke_prod`. These modules were an import-only path that read
a pre-cutover `.sqlite3` snapshot exactly once — self-described as "not a live
runtime surface." They have no non-archival importer and are the last live-tree
code that reads SQLite for Yoke's own state. Retaining them keeps a dead SQLite
reader in the tree that contradicts the Postgres-only substrate posture.

## Disposition

Retired without a fresh apply: there is nothing to apply — the historical cutover
already ran and is not repeatable. The archived SQLite snapshot referenced by the
tooling remains under `docs/archive/` as the immutable historical floor; it is no
longer read by live code. The managed-project SQLite lane (webapp template,
validation surfaces, migration-runner `sqlite_file` targets, and the guards that
support them) is unaffected — that is a distinct, live capability, not authority
tooling.
