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
