# Org scope for auth: organizations, `actor_org_roles`, org-then-project permission resolution

Status: applied to prod 2026-06-09 (founder build, no ticket — operator-driven slices)
Project: yoke
Date: 2026-06-09

## Problem

Authorization has exactly one scope today: `actor_project_roles` (actor × project ×
role). Genuinely *global* capabilities had nowhere to live, so they were stuffed into
per-project roles:

- `system.admin` ("administer the Yoke deployment") rode along on the per-project
  `owner`/`system` roles, so "owner of buzz" implied instance-wide admin — a category
  error.
- `owner` and `system` were permission-identical; the human/core distinction was only
  `actors.kind`.

Separately, item references leaked the bare global row id as a *naming* handle across
boundaries (CLI `items get 1882` resolved by global id, hardcoding the `YOK-` prefix),
which broke once a second project (`buzz`, prefix `BUZ`) existed.

## Decisions

1. **Two authorization scopes.**
   - **Org/instance scope** (new): `actor_org_roles` (actor × org × role). Carries the
     global capabilities (`org.admin`, project creation, cross-project admin).
   - **Project scope** (existing): `actor_project_roles`. Project-scoped capabilities
     only.
2. **`organizations` table; every project belongs to exactly one org.** Transfer to a
   different org is a future capability (no UI/flow now). Any number of orgs is
   supported; we seed one default org that owns both `yoke` and `buzz`.
3. **Role taxonomy.**
   - Rename role `system` → `admin`. `admin` is the **org** role.
   - Org roles: `admin`, `viewer`.
   - Project roles: `owner`, `operator`, `viewer` (unchanged set; cleaned permissions).
4. **Permission taxonomy.**
   - Rename permission `system.admin` → `org.admin`.
   - `org.admin` and a new `project.create` are **org-scoped** (not grantable on a
     project role).
   - Remove `org.admin` from every project role.
5. **Resolution is org-then-project.** A permission check resolves the target project's
   org, checks the actor's org grants first (org `admin` ⇒ all permissions on every
   project in that org); falls back to the actor's project grant otherwise.
6. **Item references are project-scoped names; the surrogate row id is internal only.**
   A single shared resolver (`resolve_cli_item_ref`) turns a CLI/API token into an
   internal `items.id`:
   - `slug/PREFIX-seq` → explicit cross-project name
   - `PREFIX-seq` → by public prefix (self-describing)
   - bare `seq` → sequence within the resolved project context
   - a real `int` passed programmatically → internal row-id passthrough (never at the
     string boundary)
   - **Bare-number project context ladder:** explicit arg → cwd checkout
     (`machine_config.project_id`) → the actor's accessible projects (org ∪ project
     grants) → machine-installed set as tiebreaker → **fail loudly** on real ambiguity.
     The actor-accessible set is a hard constraint over every path. "No grants
     recorded" is treated as unconstrained only until grants exist; we are populating
     grants now, so the founder actor is constrained to its granted orgs/projects.

## Schema

```sql
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

ALTER TABLE projects ADD COLUMN org_id INTEGER REFERENCES organizations(id);

CREATE TABLE actor_org_roles (
    actor_id INTEGER NOT NULL REFERENCES actors(id),
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    granted_at TEXT NOT NULL,
    granted_by_actor_id INTEGER REFERENCES actors(id),
    PRIMARY KEY (actor_id, org_id, role_id)
);
CREATE INDEX idx_actor_org_roles_org ON actor_org_roles(org_id);
CREATE INDEX idx_actor_org_roles_role ON actor_org_roles(role_id);
```

Roles and permissions stay shared across scopes (one `roles`/`permissions` catalog);
*scope* is determined by which grant table the role is referenced from, plus which
permissions a role carries.

## Bootstrap data

- One organization `default` (name "Default Org").
- `projects.org_id` set to the default org for `yoke` (1) and `buzz` (2).
- Grant human actor (id 2) org role `admin` on the default org → implies all projects.
- The `yoke-core` system actor (id 1) gets org `admin` on the default org (replaces
  its conceptual all-access).

## Role/permission matrix (after)

Org roles:
- `admin`: every permission (org + project), incl. `org.admin`, `project.create`.
- `viewer`: read-only (`items.read`, `events.read`) across the org's projects.

Project roles (org-scoped perms removed):
- `owner`: all project-scoped perms incl. `project.admin`. **No `org.admin`.**
- `operator`: project ops (items/claims/events/hooks/board/install). No admin.
- `viewer`: `items.read`, `events.read`.

## Permission resolution (org-then-project)

`permission_decision(conn, actor_id, project_id, permission_key)`:
1. Resolve `project.org_id`.
2. If the actor holds an org role on that org whose permissions include the key → allow
   (role evidence tagged org-scope).
3. Else fall back to the actor's project role(s) on `project_id` (existing query).
4. Allow iff either scope grants it.

## Migration plan (governed discipline, no ticket)

> Historical record. The migration module and its Postgres rehearsal test named
> below were retired after the prod apply (single-authoritative-install rule);
> the fresh-init path (`auth_schema` + `schema_init`) carries the same shape for
> new installs, and the `migration_audit` row is the durable apply evidence. The
> file paths below are pre-retirement provenance, not live surfaces.

- Idempotent module `runtime/api/domain/migrations/org_auth_scope.py` with
  `apply(conn)` + `invariants(conn)`: create `organizations`, add `projects.org_id`,
  create `actor_org_roles`; rename role `system`→`admin`; rename permission
  `system.admin`→`org.admin`; reseed `role_permissions` to the new matrix (delete +
  reinsert from the catalog); seed default org; set `projects.org_id`; grant founder +
  system actor org `admin`.
- Fresh-DB path updated in parallel (`auth_schema.create_auth_tables` +
  `schema_init`) so new installs build the same shape.
- `migration_strategy = additive_only` for the new tables/column; the role/permission
  reseed is a controlled catalog rewrite guarded by `invariants`.
- Rehearse on a disposable validation Postgres (run `apply`+`invariants`, verify),
  snapshot prod Aurora, then apply to prod with verification. Final prod apply is
  operator-confirmed.

## Slices

1. Schema + catalog: `organizations`/`actor_org_roles` DDL, `projects.org_id`,
   `actor_permissions` taxonomy (rename system→admin, system.admin→org.admin, org role
   set, reclassified matrix, org-scope tag), seed helpers, `schema_init` wiring, the
   migration module. Tests.
2. Permission resolution org-then-project (`actor_permissions`,
   `yoke_function_permissions`). Tests.
3. Grant surfaces: `grant_actor_org_role` + a sanctioned CLI for org/project grants and
   listing. Tests.
4. Shared `resolve_cli_item_ref` + bare-number ladder + actor-access constraint; delete
   the three bespoke `YOK-` parsers; fix the read/mutation adapters. Tests.
5. Bootstrap data lives in the migration (default org, associations, founder + system
   grants). Rehearse → snapshot → prod apply → verify.
6. Docs, schema_api_context packets, doctor schema-expected HC.

## Apply record (prod, 2026-06-09)

Applied via a one-shot operator-directed governed tool (snapshot → lease →
apply+invariants → audit row), since retired with the migration module per the
single-authoritative-install retirement rule (the `migration_audit` row +
this record are the durable evidence). Ticket ceremonies were skipped per
operator instruction; the governed safety contract was honored end to end:

- **Rehearsal**: `test_org_auth_scope_postgres.py` — `apply`+`invariants` on a
  disposable real-Postgres DB rewound to the legacy pre-migration shape. Green
  before prod was ever touched. (The whole org-auth authority surface —
  migration, permission resolution, item-ref resolver, grant CLI — was
  converted SQLite→Postgres so no SQLite-shaped proof backs Yoke authority.)
- **Snapshot**: RDS cluster snapshot `prod-db-cluster-pre-org-auth-scope-20260609-150817`
  taken and confirmed `available` before any mutation (rollback point).
- **Apply**: under the `LIVE_DB_MIGRATION:primary` coordination lease. Deltas —
  permissions 11→12 (`system.admin`→`org.admin` rename + new `project.create`),
  role_permissions 33→33 (catalog reseed), organizations 0→1, actor_org_roles
  0→2 (human + yoke-core bootstrapped), `projects.org_id` populated for both.
- **Audit**: `migration_audit` row `name='org-auth-scope' state='completed'` via
  the documented `record_audit_fingerprint` exception pathway (this record is
  the paired decision record).
- **Verify**: invariants + read-only checks green on prod — legacy `system`
  role/`system.admin` perm gone, `admin`/`org.admin`/`project.create` present,
  every project owns an org, default org owns both `yoke`+`buzz`, a human
  actor holds org `admin`.

## Surfaced defect: Gen 3 sequence backfill (fixed here)

Verifying the resolver against prod surfaced that the Gen 3 per-project-numbering
cutover backfilled `project_sequence = items.id` for **every** item in both
projects (so `BUZ-662` is global id 662 wearing a `BUZ` prefix; buzz's band is
662..1882, never starting at 1). The live allocator returned the smallest-unused
sequence from 1, so the next buzz item would have been `BUZ-1` — colliding
backward into already-issued number space. Fixed `allocate_project_sequence` to
continue from `MAX(project_sequence) + 1` per project (monotonic handle, never
reuses a gap, never collides backward). Proven in
`test_allocate_project_sequence.py` on real Postgres. A true per-project
*renumber* (buzz → BUZ-1..89) was considered and rejected: it would break every
issued reference (commits, GitHub issues, links). Backfilled `seq == id` also
makes prod data unable to distinguish per-project resolution from a global-id
passthrough — the synthetic PG test (sequence 5 on internal ids 100/200) is the
honest proof of per-project resolution.

## Out of scope (now)

- Project→org transfer flow/UI.
- Org-level `member`/`operator` roles (only `admin`+`viewer`).
- API-token auth changes; token issuance stays as-is.
- Multi-tenant org management UI.
- True per-project sequence renumber (rejected above; would break references).
