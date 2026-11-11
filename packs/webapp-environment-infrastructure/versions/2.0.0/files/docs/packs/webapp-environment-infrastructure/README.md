# Web Application Environment Infrastructure Pack

Composes the cloud resources needed for one deployable web application
environment: an existing VPS origin, managed Postgres, API routing, runtime
permissions, logs, and a private artifact bucket. It depends on the smaller
infrastructure Packs that supply those components.

This Pack is useful when a project wants that full topology. Projects with a
different hosting or database model should install the smaller component Packs
and keep their own environment composition instead.

See `environment.md` for configuration, required project decisions, and the
review-before-apply workflow.
