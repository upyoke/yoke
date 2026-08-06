# Capabilities

Workbench **Capabilities** lists providers, models, and test resources Yoke
may use for a project.

Examples: cloud credentials (`aws-admin`), model providers, CI workflow
binding, browser/machine QA, runner fleets.

## Ownership

- Non-secret settings: `project_capabilities` / environment settings
- Secrets: machine-local capability secret files under
  `~/.yoke/secrets/capability-secrets/<project>/...` (capability-owned — not
  ambient shell exports)
- Pack install settings specialize generic Pack source for the project; they
  are not the runtime secret store

Add or edit from the Capabilities page action / Project settings. Prefer
Yoke resolvers that materialize credentials into subprocess env without
printing secret values.
