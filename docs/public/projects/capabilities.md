# Capabilities

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Projects](index.md) > Capabilities
<!-- /yoke:breadcrumbs -->

Web dashboard **Capabilities** lists providers, models, and test resources Yoke
may use for a project.

Examples: cloud credentials (`aws-admin`), model providers, CI workflow
binding, browser/machine QA, runner fleets.

The capability roster is available through `yoke projects capabilities list`. Use `--project P` to select one project; omit it to read across projects. Lists accept `--limit N` and `--offset N` (25 rows by default); follow the printed next-page command. `--json` retains every field in the selected page.

## Ownership

- Non-secret settings: `project_capabilities` / environment settings
- Secrets: machine-local capability secret files under
  `~/.yoke/secrets/capability-secrets/<project>/...` (capability-owned — not
  ambient shell exports)
- Pack install settings specialize generic Pack source for the project; they
  are not the runtime secret store

The Capabilities page is a readiness inventory. Capability setup is performed
through the CLI or an agent; the dashboard has no setup or creation controls.
Use `yoke projects capability-settings set --help` for required settings and
creation options; `--new` creates a capability and `--base` protects an update
against concurrent changes. Prefer Yoke resolvers that materialize credentials
into subprocess env without printing secret values. A bare cloud command such
as `aws ...` reads only ambient shell credentials, so it may fail or reach the
wrong account. To check a credential, verify that the key exists or show
redacted evidence; never print the value.

Runner fleets expose the strict boolean `lifecycle.writers_paused`, default
false. True renders `webapp-infra:lifecycle_writers_paused` and holds webhook,
bootstrap and reaper Lambda reserved concurrency at zero. The digested
authority intent includes this value. Adopt matching Self-hosted Runners and
Pulumi Foundation Pack updates together, snapshot and convert existing SSM
instants while paused, and qualify exact producer hashes before resuming.

An existing fleet's initial pause sets `lifecycle.code_frozen=true` alongside
`writers_paused=true`. It retains deployed Lambda producer inputs through
Pulumi ignoreChanges; refresh/preview and exact old-code/config hash proof
precede apply, and maximum-timeout drain precedes clearing the code freeze.
Writers remain paused during strict code upgrade and SSM repair. False
controls do not change ordinary authority envelopes.
