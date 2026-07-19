# Ephemeral Environments Pack

Adds GitHub Actions workflows that build, deploy, list, and remove temporary
branch versions of a FastAPI API and Next.js web app on one Docker host. The
separate Branch Preview Hosting Pack supplies wildcard routing and scheduled
cleanup.

## Project-specific work

- Choose which branches create previews and adjust the workflow triggers.
- Connect SSH secrets and confirm the host has the Branch Preview Hosting Pack
  configured with the same namespace, domain, and port range.
- Reconcile the copied production environment, data volume, health endpoint,
  build contexts, and Compose services with the actual application.
- Decide whether preview data may persist and what teardown must delete.
- Exercise first deploy, fast rebuild, hash collision, branch deletion, and
  expiration against the real application and host.

These workflows are deliberately application-shaped starting points. A project
owns and customizes them after installation.
