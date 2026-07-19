# Webapp Scaffold Pack

A FastAPI, Next.js, and app-local SQLite starting point for a new web
application. It installs application code, tests, local configuration examples,
and a basic CI workflow; every installed file becomes ordinary project-owned
source.

## What this Pack installs

- A FastAPI service with cookie authentication, health routes, background-task
  helpers, tests, and SQLite migrations.
- A Next.js application shell with login, dashboard, settings, shared UI
  components, Vitest support, and Playwright examples.
- Project-level agent guidance, a roadmap starter, environment examples,
  ignore rules, and .github/workflows/ci.yml.

It does not install Docker, Pulumi, AWS, deployment, smoke, preview-environment,
host-maintenance, or runner-fleet code. Those are separate Packs so each
capability can be installed and updated independently.

## Install-time settings

The descriptor requires only values used by scaffold files:

| Setting | Purpose |
|---|---|
| project_name | Lowercase code and resource prefix |
| project_slug | Stable Yoke project slug |
| project_display_name | Human-readable application name |
| project_description | One-line application description |
| api_port | Local API port |
| web_port | Local web port |

Values come from the registered project's Yoke settings; secrets never enter
the Pack bundle or receipt.

## Install

Preview first:

    yoke packs get webapp-scaffold /path/to/project --project <project>

Review every created file and conflict, then apply:

    yoke packs get webapp-scaffold /path/to/project --project <project> --apply

The apply writes .yoke/packs.json. Commit the installed code and receipt
together after the project review.

## Intentional project-specific gaps

The scaffold is deliberately not a finished product. Before calling it
functional, the project must:

1. Replace sample copy, routes, data models, navigation, and visual styling.
2. Choose its real identity, authorization, persistence, migration, backup,
   secret, logging, telemetry, and incident models.
3. Decide whether app-local SQLite remains appropriate or adapt the application
   layer to another database.
4. Add domain behavior and tests.
5. Select and configure only the runtime and delivery Packs it actually needs.
6. Replace these generic notes with project-owned operating and recovery
   runbooks.

See customization.md for ownership and update guidance and development.md for
the installed development surface.

## Local development

    cd app
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    python3 db/init_db.py
    pytest

    cd app/web
    npm install
    npm run dev

Copy .env.example to an ignored .env file and replace every example secret
before using the application outside local development.

## Add independent capabilities

Inspect the catalog and preview only the capabilities the project needs:

    yoke packs list --project <project>
    yoke packs get container-runtime /path/to/project --project <project>
    yoke packs get pulumi-foundation /path/to/project --project <project>
    yoke packs get production-deploy /path/to/project --project <project>

Each selected Pack carries its own dependencies and setup gaps. The scaffold
does not imply that all web applications need the same infrastructure.

## Update

    yoke packs update webapp-scaffold /path/to/project --project <project>

Yoke three-way-merges the new immutable Pack version with the project's current
customizations. Non-overlapping changes are previewed normally; overlapping
changes become explicit conflicts. Yoke does not police unrelated project
changes, automatically delete project files, or expect customized files to be
reported back to the Pack source.
