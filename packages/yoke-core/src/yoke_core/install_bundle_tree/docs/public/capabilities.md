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

The Capabilities page is a readiness inventory. Its **Set up a capability**
disclosure links to Packs and GitHub setup and names the custom-settings CLI.
Use `yoke projects capability-settings set --help` for required settings and
creation options; `--new` creates a capability and `--base` protects an update
against concurrent changes. Prefer Yoke resolvers that materialize credentials
into subprocess env without printing secret values.
