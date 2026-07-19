# Ephemeral Environments Pack

Provides preview-environment workflows, port allocation, nginx routing, and
cleanup helpers for branch-scoped deployments.

## Project-specific work

- Choose branch eligibility, concurrency, TTL, port ranges, and host paths.
- Connect the workflow to the project's build, data-seeding, and secret model.
- Reconcile nginx and TLS behavior with the project's real domain layout.
- Define what preview data may persist and what teardown must remove.
- Exercise deploy, rerun, expiration, and teardown on the actual host.
