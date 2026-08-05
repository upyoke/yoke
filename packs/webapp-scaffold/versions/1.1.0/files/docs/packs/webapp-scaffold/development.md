# Webapp Scaffold Development Reference

## Installed backend

| Area | Main paths |
|---|---|
| FastAPI application | app/api/ |
| Authentication and request dependencies | app/api/auth.py, app/api/dependencies.py |
| Routers | app/api/routers/ |
| Background tasks and progress | app/api/tasks/ |
| SQLite schema and migrations | app/db/ |
| Shared application helpers | app/utils/ |
| Pytest coverage | app/tests/ |

## Installed frontend

| Area | Main paths |
|---|---|
| Next.js routes and layouts | app/web/src/app/ |
| Shared components | app/web/src/components/ |
| API and type helpers | app/web/src/lib/ |
| Client state | app/web/src/store/ |
| Unit-test support | app/web/src/test/ |
| Playwright examples | app/web/e2e/ |

## Local commands

Backend:

    cd app
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    python3 db/init_db.py
    pytest
    uvicorn api.main:app --reload

Frontend:

    cd app/web
    npm install
    npm run dev
    npm run build

The exact commands should be recorded in the project's Yoke Project Structure
after the project chooses its package manager and test policy.

## CI

The Pack installs only .github/workflows/ci.yml. Review its runtime versions,
dependency caching, test commands, and branch triggers before relying on it.
Delivery workflows are intentionally outside this Pack.

## Adding application code

- Add API routers under app/api/routers/ and mount them in api/main.py.
- Add schema changes through migrations rather than editing production state.
- Add web routes under app/web/src/app/.
- Add reusable UI through the project's chosen component workflow.
- Keep domain-specific services, scheduled jobs, queues, and third-party
  integrations in the project; the scaffold cannot guess them.

## Migration contract

Migration entries under `app/db/migrations/` are permanent files named
`NNNN_slug.py`. Each exposes `apply(conn)` and may expose `invariants(conn)`;
mutation, invariants, the filename-stem membership row, and its serving floor
commit in one transaction. Sequence numbers order entries but never decide
whether one is pending, so a lower-numbered entry merged later still runs.

An entry containing `DROP TABLE` or `DROP COLUMN` declares
`MINIMUM_SERVING_VERSION`, the oldest application version safe against the
result. Boot applies the pending membership set before serving. The public
health endpoint fails when history is pending, an old numeric ledger row
cannot be mapped to its permanent filename, or this build is below a recorded
serving floor. Keep migration files forever; the ledger can only reconstruct
old numeric rows while their matching history remains present.

Every apply path requires a non-empty artifact version. Boot supplies the API
version; a manual run names it explicitly:

    python3 app/db/migrations/migrate.py --running-version 0.1.0

Before pending work, the runner creates a WAL-consistent, integrity-checked
backup under `app/data/migration-backups/`, or the directory selected by
`APP_MIGRATION_BACKUP_DIR`. `--external-restore-point` may name an already
established restore point instead. The result and any failure name the path or
external identifier; a current no-op boot creates no backup.

## Relationship to other Packs

| Need | Pack |
|---|---|
| Docker and core-service runtime | container-runtime |
| Pulumi composition | pulumi-foundation |
| VPS provisioning | vps-hosting |
| DNS, API edge, and CDN | domain-cdn-edge |
| Registry and GitHub OIDC | registry-oidc |
| Production and hotfix delivery | production-deploy |
| Post-deploy smoke workflow | smoke-testing |
| Branch previews | ephemeral-environments |
| Host cleanup | host-maintenance |
| Managed Postgres infrastructure | managed-database |
| Self-hosted Actions runners | self-hosted-runners |

Installing another Pack does not make its project-specific gaps disappear;
read and complete that Pack's installed documentation.
