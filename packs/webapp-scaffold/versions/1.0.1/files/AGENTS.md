# AGENTS.md

> Think carefully and implement the most concise solution that changes as little code as possible.

## What is {{project_display_name}}

{{project_description}}. Python/FastAPI backend, Next.js/shadcn dashboard, app-local SQLite database. Early development stage.

## Key References

Read these before working on any area:

| Doc | What it covers |
|-----|----------------|
| [ROADMAP.md](ROADMAP.md) | Future work: epics, features, backlog (human-edited) |

## Yoke Operating Layer

{{project_display_name}} is operated through **Yoke** -- an attachable operating system for software delivery, in the [yoke](https://github.com/upyoke/yoke) repo. All work is tracked as Yoke backlog items (`project={{project_name}}`).

- **Backlog and board:** Managed via Yoke product CLI and `/yoke` skills. Do not create GitHub Issues directly -- all items flow through Yoke's pipeline.
- **Deployment:** GitHub Actions workflows in `.github/workflows/`. Yoke orchestrates post-merge deployment and smoke testing automatically.
- **Worktrees:** Feature work happens in Git worktrees under `.worktrees/`. Never commit implementation code directly to `main`.
- **Database boundary:** This app's SQLite database is local product data
  (`APP_DB_PATH`), not Yoke authority. Yoke project state lives in Yoke's
    Postgres control plane; never aim Yoke operations at this app DB or at the
    retired worktree-local `data/yoke.db` path.

## Deployment

Production deploys go through GitHub Actions -- never deploy manually to the server.

| Workflow | Purpose |
|----------|---------|
| `ci.yml` | CI: backend pytest + frontend build |

## Testing

This scaffold follows the four-tier test model:

- **quick** — fast unit-ish signal
- **full** — everything including browser integration tests (mocked APIs)
- **e2e** — real end-to-end against a deployed backend (not configured by default; wire up when you have a deployment to target)
- **smoke** — shallow real-stack checks against a deployed URL

```bash
# Backend (from app/)
python3 -m pytest tests/ -v

# Frontend unit (from app/web/)
npm run test

# Browser integration tests — mocked APIs, local dev server started by the Playwright config (from app/web/)
npm run test:browser

# Smoke tests against a deployed URL (requires SMOKE_BASE_URL — see .env.example)
SMOKE_BASE_URL=https://example.com npm run test:smoke

# Full verification
cd app && python3 -m pytest tests/ && cd web && npm run test && npm run build && npm run test:browser
```

Browser integration tests are distinct from smoke and E2E: `test:browser` mocks every API call with `page.route()` interception, while `test:smoke` (and any future `test:e2e`) hits a real backend via `SMOKE_BASE_URL` / `BASE_URL`.

## Local Python Setup

Use an isolated Python environment to avoid dependency conflicts with global site-packages:

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Conventions

- **Backend**: Python 3.11+. FastAPI + SQLite WAL. Pydantic models for request/response.
- **Frontend**: Next.js 16, React 19, TypeScript, shadcn/ui, TanStack Query, Zustand. MSW for test mocking.
- **CI**: GitHub Actions -- backend pytest, frontend build.

## Code Style

Follow existing patterns in the codebase. No over-engineering. Minimal changes.
