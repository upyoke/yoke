# {{project_display_name}} -- Roadmap

## What {{project_display_name}} Is

{{project_description}}.

## Architecture Summary

| Component | Tech | Port |
|-----------|------|------|
| API | Python 3.11+ / FastAPI / Pydantic v2 | {{api_port}} |
| Dashboard | Next.js 16 / React 19 / TypeScript / Tailwind v4 / shadcn/ui | {{web_port}} |
| App database | app-local SQLite (WAL mode) | file-based product data |
| CI | GitHub Actions (pytest + npm build) | -- |

## What's Been Completed

- Project started from the Yoke Webapp Scaffold Pack
- Auth system (cookie-based sessions, multi-tenancy)
- Dashboard shell (sidebar, top bar, settings)
- Health endpoint

---

## Planned Work

Add epics and phases here as the project evolves.

---

## Yoke Operating Layer

This project is operated through **Yoke** (project: {{project_name}}). Backlog, delivery flows, deployment state, and work tracking live in Yoke's Postgres control plane, not in this app's SQLite database. See Yoke's BOARD.md for the current work state.
