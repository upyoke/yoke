# Container Runtime Pack

Provides a starting Docker, Compose, entrypoint, and nginx layout for a Python
API plus a Next.js web application.

## Project-specific work

- Choose final image names, build contexts, ports, persistent volumes, and
  process commands.
- Connect project secrets and environment variables without committing them.
- Reconcile the reverse proxy and health checks with the project's real routes.
- Decide whether one or both example containers belong in this project.
- Run both container builds and the complete Compose stack before deployment.

These gaps are intentional: the Pack supplies reusable runtime structure, not
a claim that every application's processes or storage are identical.
