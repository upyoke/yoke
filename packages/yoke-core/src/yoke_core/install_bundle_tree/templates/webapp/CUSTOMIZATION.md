# Webapp Template: Customization Guide

How to adapt this template for your project. Organized by capability area with the deviation classification framework.

## Deviation Categories

When a project diverges from the template, classify the deviation:

| Category | Definition | Action |
|----------|-----------|--------|
| **A** | Parameterizable -- expressible as `{{placeholder}}` | Fix in template + render pipeline |
| **B** | Approved non-generalizable -- legitimately project-specific | Document in `.yoke/template-deviations.md` with operator approval |
| **C** | Pure drift -- diverged without justification | Fix whichever side is wrong |

Category A deviations should be resolved by adding a new template variable. Category B deviations are expected and documented. Category C deviations are bugs.

## Category B Entry Template

When documenting a non-generalizable deviation in your project's `.yoke/template-deviations.md`:

```markdown
### {Project}: {file} -- {short description}

**Classification:** Category B (non-generalizable)
**Approved by operator:** {date or [pending]}
**Reason:** Why this project needs to diverge from the template.
**Impact on template:** Whether this affects other projects or the template itself.
**Revisit condition:** Under what circumstances this deviation could be eliminated.
```

## Customization Points by Area

### Docker Compose

The template uses bridge networking with explicit port mapping and inter-container routing via service names.

**Common customizations:**
- **Host networking:** Projects that need access to services running on the VPS host (not in Docker) may require `network_mode: host`. This eliminates port mapping, networks, and inter-container `API_URL`. Document as Category B. Note: even projects using host networking in production use bridge networking for ephemeral environments — the ephemeral deploy workflow generates a standalone `docker-compose.ephemeral.yml` with explicit port mapping and a bridge network for inter-container routing.
- **Volume names:** The template uses `app-data`. Rename via the render pipeline's `{{project_name}}` variable.
- **Additional services:** Add domain-specific services (Redis, Postgres, etc.) to `docker-compose.yml`. These are project-specific additions, not deviations.

### Dockerfile (API)

The template uses `python:3.12-slim` with minimal system dependencies (`curl` only).

**Common customizations:**
- **Base image:** Projects requiring browser automation or specialized system libraries may need a different base image (e.g., Playwright). Document as Category B.
- **System packages:** Add project-specific packages (`socat`, `jq`, `nodejs`, etc.) to the `apt-get install` line. Document as Category B if they significantly change the image.
- **Python dependencies:** Add domain-specific packages to `requirements.txt`. No deviation needed -- this is expected.
- **Build steps:** Additional build steps (e.g., `playwright install`, `npm install`) for specialized tooling. Document as Category B.

### Entrypoint

The template entrypoint runs `init_db.py` then starts uvicorn.

**Common customizations:**
- **Seed data:** Projects that need demo/default data on every startup can add a seed step. Document as Category B since not all projects should auto-seed.
- **Migration runner:** Add `python3 db/migrations/migrate.py` before the server start if using schema migrations.
- **Pre-start checks:** Add health checks for external dependencies before starting the server.

### Database Backend

**The template default is app-local SQLite, and that is intentional.** The
scaffold is a self-contained FastAPI + Next.js + SQLite + Docker product: the app
reads `APP_DB_PATH` (a file path), `utils/db.py` opens it with `sqlite3`,
`db/schema.sql` is SQLite DDL, and Yoke validates migrations against a
worktree-local SQLite surface (the `webapp_sqlite_empty` recipe). Buzz — a live
product instantiated from this template — runs on exactly this default.

This is **separate from Yoke's own control-plane database**, which is Postgres
(Aurora). The Yoke control-plane cloud runtime "Postgres-native" posture applies to Yoke's control plane,
not to every generated webapp — do **not** blind-convert this scaffold's SQLite
to Postgres. The full rationale and live evidence are recorded in
[`docs/archive/decisions/webapp-template-sqlite-default-boundary.md`](../../docs/archive/decisions/webapp-template-sqlite-default-boundary.md).

**Common customizations:**
- **Stay on SQLite (default):** No deviation needed. Add domain tables under
  "Database Schema" below; the validation surface stays `worktree_local_sqlite`.
- **Switch to managed Postgres:** A project-level override, not a template-default
  change. Declare the project `migration_model` capability with
  `authoritative_db.kind=postgres` paired with
  `validation_surface.kind=external_validation`, compose the opt-in Aurora
  component `infra/webapp_database_stack.py` into the environment stack, and adapt
  the app layer (`utils/db.py`, `schema.sql`, migrations, tests) to a Postgres
  DSN. Document as **Category B** — this is a deliberate app-architecture choice
  the default scaffold does not make for you.

### Database Schema

The template includes 4 auth tables (`orgs`, `users`, `org_members`, `sessions`).

**Common customizations:**
- **Domain tables:** Add project-specific tables to `db/schema.sql` or via migrations. No deviation needed.
- **Performance indexes:** Add indexes as needed for your query patterns.
- **Schema header:** Updated automatically via `{{project_display_name}}` placeholder.

### API Routers

The template includes 2 routers (`auth`, `system`).

**Common customizations:**
- **Domain routers:** Create `api/routers/{domain}.py` and mount in `api/main.py`. No deviation needed.
- **App title/logger:** Updated automatically via template variables.
- **Environment variables:** The template uses `APP_` prefix. Projects needing a different prefix should update `api/config.py`.

### Frontend

The template includes a dashboard shell with auth, 3 pages, 1 store, and 10 shadcn/ui components.

**Common customizations:**
- **Additional pages:** Add to `src/app/(dashboard)/{page}/`. No deviation needed.
- **Domain stores:** Create `src/store/{domain}.ts`. No deviation needed.
- **Custom hooks:** Create in `src/hooks/`. No deviation needed.
- **UI components:** Add via `npx shadcn@latest add {component}`. No deviation needed.
- **Domain components:** Create in `src/components/`. No deviation needed.

### GitHub Actions

The template includes only `ci.yml` in the scaffold. Deploy workflow material is
fetched from the product template surface with `yoke templates fetch webapp
--only ops/`, then project onboarding applies the project-specific substitutions
and commits the selected workflow files to the project repo.

**Common customizations:**
- **Deploy workflows:** Generated automatically. Customizations flow through template variables (`{{api_port}}`, `{{web_port}}`, `{{PROJECT_NAME_UPPER}}`, etc.).
- **CI modifications:** Changes to `ci.yml` should be reflected back in the template if they are generally applicable.
- **Additional workflows:** Project-specific workflows (e.g., scheduled tasks, data pipelines) are project additions, not deviations.

## Tracking Deviations

Each project that instantiates this template should maintain
`.yoke/template-deviations.md`. This file serves as:

1. **Drift detection baseline** -- Know what differences are intentional vs accidental
2. **Operator approval record** -- Category B deviations require explicit approval
3. **Revisit trigger** -- Each deviation has conditions under which it can be eliminated

The `HC-template-project-drift` health check compares rendered template output against deployed project files and flags unexpected differences.
