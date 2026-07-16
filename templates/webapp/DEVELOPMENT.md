# Webapp Template — Development Reference

Extracted from [README.md](README.md). Included packages, CI/CD topology, adding components.

## What's Included

### Backend (app/)

| Component | Files | Purpose |
|-----------|-------|---------|
| FastAPI app | `api/main.py` | App factory, CORS, lifespan, request logging |
| Config | `api/config.py` | Settings from environment variables |
| Auth | `api/auth.py`, `api/dependencies.py` | Cookie-based sessions, password hashing, role hierarchy |
| Auth router | `api/routers/auth.py` | Login, logout, current user endpoints |
| System router | `api/routers/system.py` | Health check endpoint |
| Error handling | `api/errors.py` | Centralized error responses |
| Task runner | `api/tasks/runner.py` | Background task execution |
| SSE broadcaster | `api/tasks/progress.py` | Server-sent events for real-time progress |
| Database | `db/schema.sql`, `db/init_db.py` | Schema, initialization, WAL mode |
| Migrations | `db/migrations/migrate.py` | Python migration modules and schema version tracking |
| Seed data | `db/seed_users.py` | Default org and admin user |
| DB utils | `utils/db.py` | SQLite WAL connection management |
| LLM client | `utils/llm.py` | Optional Anthropic API client |
| Tests | `tests/conftest.py`, `tests/test_api_*.py` | Pytest fixtures and endpoint tests |

> **Database backend.** The app database is app-local SQLite by design (this is
> not the same concern as Yoke's own Postgres control plane, and not Yoke control-plane cloud runtime
> SQLite residue). Switching a project to managed Postgres is a project-level
> override, not a template-default change — see
> [CUSTOMIZATION.md → Database Backend](CUSTOMIZATION.md#database-backend).

### Frontend (app/web/)

| Component | Files | Purpose |
|-----------|-------|---------|
| Next.js app | `src/app/layout.tsx`, `src/app/page.tsx` | Root layout, home redirect |
| Login | `src/app/login/page.tsx` | Login form with API integration |
| Dashboard shell | `src/app/(dashboard)/layout.tsx` | Sidebar + top bar layout |
| Dashboard page | `src/app/(dashboard)/dashboard/page.tsx` | Default dashboard view |
| Settings | `src/app/(dashboard)/settings/page.tsx` | User settings page |
| Auth middleware | `src/middleware.ts` | Route protection via cookie check |
| API client | `src/lib/api.ts` | Fetch wrapper for backend API |
| Auth store | `src/store/auth.ts` | Zustand store for auth state |
| Providers | `src/components/providers.tsx` | TanStack Query + Sonner toast |
| Sidebar | `src/components/sidebar.tsx` | Navigation sidebar |
| Top bar | `src/components/top-bar.tsx` | Header with user menu |
| UI components | `src/components/ui/` | 10 shadcn/ui base components |
| Tests | `src/test/setup.ts`, `src/test/test-utils.tsx` | Vitest + MSW test infrastructure |
| E2E | `e2e/auth.spec.ts`, `e2e/playwright.config.ts` | Playwright end-to-end tests |

### Infrastructure

| Component | Files | Purpose |
|-----------|-------|---------|
| Pulumi infra stack | `infra/__main__.py` (infra stack) | Route 53 + ACM + CloudFront + DNS records |
| Pulumi VPS stack | `infra/__main__.py` (vps stack) | EC2 + Elastic IP + security group |
| Pulumi config | `infra/Pulumi.yaml`, `infra/Pulumi.{{pulumi_infra_stack_name}}.yaml`, `infra/Pulumi.{{pulumi_vps_stack_name}}.yaml`, `infra/requirements.txt` | Pulumi project + per-stack config + Python deps |
| Docker Compose | `docker-compose.yml` | API + Web services with bridge networking |
| API Dockerfile | `app/Dockerfile` | Python container with entrypoint |
| Web Dockerfile | `app/web/Dockerfile` | Node.js container for Next.js |
| CI | `.github/workflows/ci.yml` | pytest + npm build on push/PR |
| Deploy | `ops/deploy.yml` | Production workflow invoked by the project's normal release flow |
| Hotfix | `ops/hotfix.yml` | Direct-to-production workflow invoked by the project's hotfix flow |
| Smoke | `ops/smoke.yml` | Post-deploy smoke test |
| Ephemeral deploy | `ops/ephemeral-deploy.yml` | Deploy preview env on branch push |
| Ephemeral teardown | `ops/ephemeral-teardown.yml` | Tear down preview env on PR merge/close |
| Ephemeral cleanup | `ops/ephemeral-cleanup.sh.tmpl` | Cleanup script for stale ephemeral envs (renders to `<render-output>/ops/ephemeral-cleanup.sh`) |
| Environment | `.env.example` | Template for environment variables |
| Git ignores | `.gitignore`, `app/.dockerignore`, `app/web/.dockerignore` | Standard ignore patterns |
| Project docs | `AGENTS.md`, `CLAUDE.md` (compat symlink), `ROADMAP.md` | Project documentation templates |

## CI/CD Workflow Topology

The template includes 6 GitHub Actions workflows that form a complete CI/CD pipeline. Fetch workflow material with `yoke templates fetch webapp --only ops/`; project onboarding applies project-specific substitutions and commits the selected files to the project repo.

### Workflow trigger map

```
Branch push (non-main)
  ├── CI (ci.yml)                     — pytest + npm build
  └── Ephemeral Deploy (ephemeral-deploy.yml) — preview env on VPS

Pull request opened/updated
  └── CI (ci.yml)                     — pytest + npm build

PR merged / branch deleted
  └── Ephemeral Teardown (ephemeral-teardown.yml) — destroy preview env

Push to main (after PR merge)
  └── CI (ci.yml)                     — pytest + npm build

Yoke deployment run
  ├── Normal production flow
  │    ├── Deploy (deploy.yml)         — rsync to VPS, docker compose up
  │    └── Smoke (smoke.yml)          — post-deploy health gate
  └── Production hotfix flow
       └── Hotfix (hotfix.yml)         — direct-to-prod deploy
```

### Ephemeral environments

Every push to a feature branch automatically deploys an isolated preview environment on the same VPS as production. Each branch gets deterministic port offsets derived from a hash of the branch name:

- **API port:** 9000 + (hash % 100) — range 9000-9099
- **Web port:** 4000 + (hash % 100) — range 4000-4099

Production uses `{{api_port}}`/`{{web_port}}`, so these ranges never collide. Supports up to 100 concurrent ephemeral environments.

Ephemeral environments are:
- **Created** on every branch push (except `main` and `hotfix/**`)
- **Updated** on subsequent pushes to the same branch
- **Destroyed** when the PR is merged or the branch is deleted
- **Isolated** — each gets its own directory (`~/{{project_name}}-ephemeral/<slug>/`), Docker Compose project, and port pair

The environment URL is available in the GitHub Actions run output.

**Note:** CI and ephemeral workflows trigger on git events (push/PR). Normal
and hotfix delivery start from the work item's project-local Yoke deployment
flow, which dispatches and correlates the repository workflows.

### Why build steps repeat

Yoke's merge engine reads the project-specific `merge_verification` policy from Project Structure and runs that command before merge using that policy's `timeout_seconds` budget. When no policy is configured, the merge engine logs `[phase:tests] no merge policy configured for project '<id>' -- skipping project tests` and proceeds without running anything; it does not silently fall back to `command_definitions.full` or any other command. Existing installs are not backfilled with a merge policy automatically, so merge-time project tests skip until onboarding records the explicit policy. For typical webapp projects this is the project's `quick` command surface (fast unit-test signal). The GitHub Actions CI workflow also runs a clean-environment `npm run build`, and both deploy workflows rebuild the Docker image on the VPS. The overlap between merge-time verification and CI/deploy is intentional defense in depth:

- Local merge verification catches breakage before a PR or merge lands.
- CI proves the branch still passes on a clean Ubuntu runner with pinned tool setup.
- Ephemeral and production deploys rebuild inside the actual `node:20-alpine` container context that will serve the app. Production deploy and hotfix workflows use a readiness-gated fast-path: when existing production containers are healthy, Docker layer caching is reused for faster rebuilds; when readiness fails or `force_rebuild` is set, the full `--no-cache` cold-start path runs.

Those stages are similar, but they are not equivalent. Keep the overlap unless a future optimization can prove that an earlier successful stage covers the same commit SHA and execution environment.

## Adding shadcn/ui Components

The scaffold includes 10 base components. To add more:

```bash
cd app/web
npx shadcn@latest add <component-name>
```

For example:

```bash
npx shadcn@latest add table tabs textarea badge progress switch
```

The `components.json` file is pre-configured with the correct paths and aliases.

## Adding Domain Routers

The scaffold includes only `auth` and `system` routers. To add domain-specific routers:

1. Create `app/api/routers/your_domain.py`
2. Import and mount in `app/api/main.py`:

```python
from api.routers.your_domain import router as your_domain_router
app.include_router(your_domain_router)
```

3. Add domain tables to `app/db/schema.sql` or create a Python migration module in `app/db/migrations/`

## Adding Domain Stores and Hooks

The scaffold includes only the `auth` store. To add domain-specific state:

1. Create `app/web/src/store/your_domain.ts`
2. Create hooks in `app/web/src/hooks/` (e.g., `useYourDomain.ts`)
3. Add dashboard pages in `app/web/src/app/(dashboard)/your-domain/`

## Going-Forward Enforcement

When modifying infrastructure files in a project instantiated from this template, check whether the change should be reflected back in the template. The template and its instances are not automatically synchronized.

Key infrastructure files to keep in mind:

- Auth system (`api/auth.py`, `api/dependencies.py`, `api/routers/auth.py`, `src/middleware.ts`)
- Database layer (`utils/db.py`, `db/init_db.py`, `db/migrations/migrate.py`)
- Docker setup (`docker-compose.yml`, Dockerfiles, `entrypoint.sh`)
- CI workflow (`.github/workflows/ci.yml`)
- Test infrastructure (`tests/conftest.py`, `src/test/setup.ts`)

See [CUSTOMIZATION.md](CUSTOMIZATION.md) for the customization guide and deviation classification framework.
