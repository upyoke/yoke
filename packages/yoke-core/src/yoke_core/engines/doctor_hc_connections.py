"""Machine-local credential files and operating-actor bindings."""

from pathlib import Path
import shlex

from yoke_cli.config import machine_config, secrets
from yoke_contracts.machine_config import schema
from yoke_core.domain import db_backend
from yoke_core.domain.session_actor_binding import resolve_operating_actor
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

SLUG = "connections"
TITLE = "Connection credentials and operating actors"


def repair_command(env, entry):
    if env == "local" and entry.get("transport") == schema.DEFAULT_TRANSPORT:
        return "yoke init --local"
    return f"yoke --env {shlex.quote(env)} setup"


def connection_issues(env, entry):
    """Return named, redacted findings without changing any connection."""
    recovery = repair_command(env, entry)
    source = entry.get("credential_source") or {}
    kind = source.get("kind")
    if kind in {schema.CREDENTIAL_KIND_DSN_FILE, schema.CREDENTIAL_KIND_TOKEN_FILE}:
        path = source.get("path")
        if not path or not Path(path).expanduser().is_file():
            return [
                (
                    "FAIL",
                    f"CONNECTION_CREDENTIAL_FILE_MISSING: connection {env!r} has no credential file. Repair: `{recovery}`.",
                )
            ]
    if not entry.get("operating_actor"):
        return []
    if kind != schema.CREDENTIAL_KIND_DSN_FILE:
        return [
            (
                "WARN",
                f"CONNECTION_ACTOR_UNVERIFIED: connection {env!r} has no direct database credential to verify its operating actor. Run `{recovery}`.",
            )
        ]
    try:
        from psycopg.conninfo import make_conninfo

        dsn = secrets.read_secret_file(source["path"], "DSN")
        conn = db_backend.connect_psycopg(make_conninfo(dsn, connect_timeout=3))
        try:
            conn.execute("SET TRANSACTION READ ONLY")
            binding = resolve_operating_actor(conn, env=env)
        finally:
            conn.close()
    except Exception as exc:
        return [
            (
                "WARN",
                f"CONNECTION_ACTOR_UNVERIFIED: connection {env!r} could not verify its operating actor ({type(exc).__name__}). Check its database is reachable, then rerun `yoke doctor run --only connections`.",
            )
        ]
    if binding.bound:
        return []
    return [
        (
            "FAIL",
            f"CONNECTION_OPERATING_ACTOR_INVALID: connection {env!r}: {binding.code}. Its operating actor is missing, invalid, or belongs to another universe. Repair: `{recovery}`.",
        )
    ]


def hc_connections(conn, args, rec):
    payload = machine_config.load_config()
    entries = payload.get("connections") or {}
    before = len(rec.results)
    for env, entry in entries.items():
        issues = connection_issues(env, entry)
        for severity, detail in issues:
            rec.record(SLUG, TITLE, severity, detail)
    if len(rec.results) == before:
        rec.record(
            SLUG,
            TITLE,
            "PASS",
            "Configured credential files and recorded operating actors are valid.",
        )


def active_connection_failure():
    """Diagnose an unusable active connection before Doctor needs its database."""
    payload = machine_config.load_config()
    try:
        env = schema.selected_env(payload)
    except schema.MachineConfigContractError:
        return None
    entry = (payload.get("connections") or {}).get(env)
    if not entry:
        return None
    issues = connection_issues(env, entry)
    if not any(severity == "FAIL" for severity, _ in issues):
        return None
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
    from yoke_core.engines.doctor_https_compose import recount

    rec = RecordCollector()
    hc_connections(None, DoctorArgs(), rec)
    rows = [
        dict(
            hc=row.check_id, name=row.check_name, severity=row.result, detail=row.detail
        )
        for row in rec.results
    ]
    return FunctionCallResponse(
        success=False,
        function="doctor.run.run",
        version="v1",
        request_id="",
        result={"results": rows, **recount(rows)},
        error=FunctionError(
            code="doctor_active_connection_unavailable",
            message="Connection diagnostics completed; remaining Doctor checks could not use the active connection.",
            recovery_hint=f"Run `{repair_command(env, entry)}`, then repeat the requested Doctor scope.",
        ),
    )
