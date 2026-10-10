# Installer Session Registration And Telemetry

Use this after a stage or prod publish that touches hooks, auth, session identity,
lane routing, telemetry, or board rendering. Run from visible Terminal or a real
SSH TTY so the user can watch the same terminal.

```bash
cd <external-project-checkout>
YOKE_ENV=stage yoke status
YOKE_ENV=stage claude -p 'Reply exactly: YOKE_STAGE_SESSION_SMOKE_OK'
YOKE_ENV=stage yoke board rebuild --print --no-pager
```

The board should show a fresh session for that external project. This is an
external-E2E campaign rather than a project-specific product path. Verify the
control plane by resolving the project through its durable slug, never an
installation-local numeric id:

```bash
YOKE_ENV=stage yoke db read "SELECT hs.session_id, hs.project_id, hs.actor_id, hs.executor, hs.executor_surface, hs.model, hs.requested_model, hs.execution_level, hs.workspace, hs.ended_at FROM harness_sessions hs JOIN projects p ON p.id = hs.project_id WHERE p.slug = '<external-project-slug>' ORDER BY hs.offered_at DESC LIMIT 5"
YOKE_ENV=stage yoke events query --project <external-project-slug> --since '20 minutes ago' --limit 50
```

Expected stage evidence: the session row's project/actor and declared harness
surface match the campaign, and the visible board matches that durable row.
Inspect any named hook refusal. Model and usage metadata may be unavailable;
missing metadata is not registration failure. Events can corroborate request
correlation, but their absence proves nothing about session registration.

For hosted API logs, use the hosting project's `aws-admin` capability on the
operator machine. Read `yoke aws exec --help` for credential/region resolution
and named prerequisite refusals. Choose the actual hosting project and log
group; the test machine does not receive these credentials:

```bash
yoke aws exec --project <hosting-project> -- logs filter-log-events --log-group-name <stage-log-group> \
  --start-time <epoch-ms-before-smoke> --filter-pattern '"POST /v1/hooks/evaluate"'
yoke aws exec --project <hosting-project> -- logs filter-log-events --log-group-name <stage-log-group> \
  --start-time <epoch-ms-before-smoke> --filter-pattern '?ERROR ?Error ?error ?Traceback ?Exception'
```

For observed hook requests, inspect HTTP outcome and redacted actor/request
correlation. An empty error scan is bounded diagnostic evidence, not proof that
every request succeeded. Never print tokens or capability secret values.

For cost-safe metric export, request correlation, and in-process scoped
debug campaigns (`YOKE_API_DEBUG_SCOPE` / `_UNTIL` / `_MAX_RECORDS`), see
[`api-observability.md`](api-observability.md). Do not put request IDs on
EMF metric attributes.
