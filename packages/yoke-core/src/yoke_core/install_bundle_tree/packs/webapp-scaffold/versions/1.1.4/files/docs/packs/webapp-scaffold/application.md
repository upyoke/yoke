# {{project_display_name}} application

{{project_description}}. The application uses a Python/FastAPI backend,
Next.js/shadcn dashboard and application-local SQLite data.
Yoke project identity: `{{project_name}}`. Operating rules remain in canonical
`AGENTS.md`; this document describes only the application.

## Source and checks

- Backend: `app/api/`; database and ordered migrations: `app/db/`.
- Frontend: `app/web/`; components and API client live under `src/`.
- Backend checks: `python3 -m pytest app/tests` in the application environment.
- Frontend checks: `npm --prefix app/web test -- --run` and
  `npm --prefix app/web run build`.
- Browser integration examples mock API calls. They do not prove a deployed
  backend. Read [development.md](development.md) for browser and smoke commands.

Use the declared application Python environment and `app/requirements.txt`.
SQLite files and WAL sidecars are application data. Follow the application
migration documentation before changing that model.

The scaffold installs CI and test entrypoints. Hosting, deployment flows and
credentials are chosen and verified separately during `/yoke onboard`.
Installing this Pack does not create or authorize a deployment.
Read [setup.md](setup.md) and [customization.md](customization.md) before adoption.
