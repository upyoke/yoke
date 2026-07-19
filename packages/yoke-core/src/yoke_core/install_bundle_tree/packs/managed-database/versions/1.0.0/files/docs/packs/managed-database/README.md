# Managed Database Pack

Provides an optional Pulumi component for a managed PostgreSQL database.

## Project-specific work

- Choose engine sizing, backup retention, deletion protection, and maintenance
  windows.
- Connect the database to the project's actual network and runtime principals.
- Decide how credentials are created, rotated, and delivered at runtime.
- Define migrations, restore testing, observability, and incident recovery.
- Import any existing database before applying this component.
