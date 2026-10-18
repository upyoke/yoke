# Server health readiness

`yoke status` checks the active server's public health document with a
10-second timeout per attempt and one retry. If both attempts fail,
`server_unreachable` names the authority and explains how to start the server
or select a reachable environment. A successful health check is followed by
a separate authenticated identity check; liveness does not prove the tenant.

`/v1/health` always serves the last complete readiness snapshot. Application
construction warms the initial snapshot; a dedicated background worker probes schema readiness, migration membership, serving
surfaces and migration content identity every 30 seconds by default, starting
when the server starts. The existing `health_migrations_probe_ttl_seconds`
machine setting controls the delay between completed probes. Health requests
perform no database probes, migration-file hashing or credential-file reads,
and do not queue for the synchronous request worker pool.

Until the first probe completes, the server stays live but reports
`schema_ready=false` and `can_serve_this_database=false`, with
`health_snapshot_pending` explaining the recovery. Failed refreshes retain the
last complete answer and log `health_snapshot_refresh_failed` with the next
step: check database connectivity and migration readiness, then retry after
the next refresh. The snapshot is a recent observation, not a guarantee that
the database is reachable at the instant of a health request.

The engine version and startup-attested public GitHub App advertisement are
resolved at startup. Build identity comes from the baked process environment.
Restart the server after changing its build or GitHub App configuration. Public health never includes private keys
or database connection details.
