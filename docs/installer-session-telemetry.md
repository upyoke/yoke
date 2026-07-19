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
YOKE_ENV=stage yoke db read "SELECT hs.session_id, hs.project_id, hs.actor_id, hs.executor, hs.display_name, hs.model, hs.execution_lane, hs.workspace, hs.ended_at FROM harness_sessions hs JOIN projects p ON p.id = hs.project_id WHERE p.slug = '<external-project-slug>' ORDER BY hs.started_at DESC LIMIT 5"
YOKE_ENV=stage yoke events query --project <external-project-slug> --since '20 minutes ago' --limit 50
```

Expected stage evidence: executor/model/lane populated, a DB-backed lane such as
`DARIUS`, no hook-denied errors, session events carrying the same project id, and
the visible board's newest session matching the DB row. Angle-bracket Claude
model values are temporary SDK placeholders and should be upgraded by later
concrete registration.

For hosted API logs, check CloudWatch from the operator machine with AWS operator
credentials, not from the test Mac:

```bash
aws logs filter-log-events --log-group-name /yoke/stage/core \
  --start-time <epoch-ms-before-smoke> --filter-pattern '"POST /v1/hooks/evaluate"'
aws logs filter-log-events --log-group-name /yoke/stage/core \
  --start-time <epoch-ms-before-smoke> --filter-pattern '?ERROR ?Error ?error ?Traceback ?Exception'
```

Expected CloudWatch evidence: hook relay requests return HTTP `200`, include the
expected actor/token/request ids, and the error scan is clean.
