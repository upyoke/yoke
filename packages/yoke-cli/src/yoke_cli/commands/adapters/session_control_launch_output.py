"""Human output for fleet launch records and machine-relay state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TextIO

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_cli.commands.adapters.session_control_human_output import (
    Column,
    EMPTY_VALUE,
    humanize,
    utc_time,
    write_summary,
    write_table,
)
from yoke_cli.commands.adapters.session_control_launch_preview_output import (
    write_launch_preview,
)
from yoke_cli.commands.adapters.session_control_native_diagnostic_output import (
    native_diagnostic_fields,
)


def _launch_status(launch: Mapping[str, Any]) -> str:
    state = humanize(launch.get("state"))
    result = humanize(launch.get("result_code"))
    return f"{state} ({result})" if result != EMPTY_VALUE else state


def _launch_identity(launch: Mapping[str, Any]) -> str:
    state = str(launch.get("identity_correlation") or "unknown")
    labels = {
        "matched": "matched",
        "mismatch": "mismatch",
        "awaiting_registration": "awaiting registration",
        "registration_failed": "registration failed",
        "native_unreported": "native identity not reported",
        "correlation_failed": (f"failed ({humanize(launch.get('result_code'))})"),
        "unavailable": "unavailable",
        "pending": "waiting for native session",
        "unknown": "status unavailable",
    }
    return labels.get(state, humanize(state))


def _instruction_delivery(launch: Mapping[str, Any]) -> str:
    state = str(launch.get("instruction_delivery") or "unknown")
    return {
        "delivered": "delivered",
        "not_delivered": "not delivered",
        "pending": "pending",
        "unknown": "status unavailable",
    }.get(state, humanize(state))


def _launch_recovery(launch: Mapping[str, Any]) -> str | None:
    if (
        launch.get("instruction_delivery") != "not_delivered"
        or launch.get("state") != "outcome_unknown"
    ):
        return None
    launch_id = str(launch.get("launch_id") or "LAUNCH-ID")
    native = str(launch.get("native_session_id") or "").strip()
    command = f"yoke session-control launch reconcile {launch_id}"
    if native:
        return f"Reconcile before retry: {command} --observed-native-id {native}"
    return (
        "Find the native session ID, then reconcile before retry: "
        f"{command} --observed-native-id ID"
    )


def _result_evidence(launch: Mapping[str, Any]) -> str | None:
    evidence = launch.get("result_evidence")
    safe_evidence = redacted_evidence_document(
        evidence if isinstance(evidence, Mapping) else None
    )
    if not safe_evidence:
        return None
    return "; ".join(f"{humanize(key)}={value}" for key, value in safe_evidence.items())


def _diagnostic_fields(launch: Mapping[str, Any]) -> list[tuple[str, Any]]:
    evidence = launch.get("result_evidence")
    return native_diagnostic_fields(
        evidence if isinstance(evidence, Mapping) else None,
        fallback_machine=launch.get("assigned_machine_id"),
    )


def _write_launch_detail(
    launch: Mapping[str, Any],
    stdout: TextIO,
    *,
    deduplicated: Any = None,
) -> None:
    fields: list[tuple[str, Any]] = [
        ("Launch ID", launch.get("launch_id")),
        ("State / result", _launch_status(launch)),
        ("Project", launch.get("project") or launch.get("project_id")),
        ("Origin", launch.get("origin")),
        ("Requested surface", launch.get("requested_surface")),
        ("Selected surface", launch.get("selected_surface")),
        (
            "Fallback used",
            bool(
                launch.get("selected_surface")
                and launch.get("selected_surface") != launch.get("requested_surface")
            ),
        ),
        ("Requested machine", launch.get("requested_machine_id")),
        ("Assigned machine", launch.get("assigned_machine_id")),
        ("Placement", launch.get("placement_reason")),
        ("Requested model", launch.get("requested_model")),
        ("Model", launch.get("resolved_model")),
        ("Fallback allowed", bool(launch.get("allow_surface_fallback"))),
        ("Native session", launch.get("native_session_id")),
        ("Registered session", launch.get("registered_session_id")),
        ("Identity correlation", _launch_identity(launch)),
        ("Instruction delivery", _instruction_delivery(launch)),
        ("Recovery", _launch_recovery(launch)),
        *_diagnostic_fields(launch),
        ("Result evidence", _result_evidence(launch)),
        ("Spawn hold", launch.get("spawn_hold_reason")),
        ("Created (UTC)", utc_time(launch.get("created_at"))),
        ("Deadline (UTC)", utc_time(launch.get("deadline_at"))),
        ("Completed (UTC)", utc_time(launch.get("completed_at"))),
    ]
    if deduplicated is not None:
        fields.insert(2, ("Deduplicated", bool(deduplicated)))
    write_summary("LAUNCH", fields, stdout)


def write_launch_result(result: Mapping[str, Any], stdout: TextIO) -> None:
    if "launches" in result:
        columns: tuple[Column, ...] = (
            ("LAUNCH", lambda row: row.get("launch_id"), None),
            ("STATE / RESULT", _launch_status, 28),
            ("PROJECT", lambda row: row.get("project") or row.get("project_id"), 14),
            ("ORIGIN", lambda row: row.get("origin"), 10),
            ("REQUESTED", lambda row: row.get("requested_surface"), 18),
            ("SELECTED", lambda row: row.get("selected_surface"), 18),
            ("NATIVE", lambda row: row.get("native_session_id"), None),
            ("REGISTERED", lambda row: row.get("registered_session_id"), None),
            ("CORRELATION", _launch_identity, 24),
            ("DELIVERY", _instruction_delivery, 16),
            (
                "MACHINE",
                lambda row: (
                    row.get("assigned_machine_id") or row.get("requested_machine_id")
                ),
                None,
            ),
            ("CREATED (UTC)", lambda row: utc_time(row.get("created_at")), 22),
            ("DEADLINE (UTC)", lambda row: utc_time(row.get("deadline_at")), 22),
        )
        write_table(
            "LAUNCHES",
            columns,
            result.get("launches") or [],
            stdout,
            empty="No launches found.",
        )
        return
    launch = result.get("launch")
    if isinstance(launch, Mapping):
        _write_launch_detail(launch, stdout, deduplicated=result.get("deduplicated"))
        return
    if "outcome" in result or "eligible_relays" in result:
        write_launch_preview(result, stdout)
        return
    print("LAUNCH\nNo launch details returned.", file=stdout)


def write_relay_probe_summary(payload: Mapping[str, Any], stdout: TextIO) -> None:
    columns: tuple[Column, ...] = (
        ("SURFACE", lambda row: row.get("surface"), 20),
        ("SOURCE", lambda row: humanize(row.get("source")), 8),
        ("VERDICT", lambda row: humanize(row.get("verdict")), 16),
        ("VERSION", lambda row: row.get("version"), 18),
        ("DURATION (MS)", lambda row: row.get("duration_ms"), 13),
        ("ADVERTISED", lambda row: row.get("advertised_version"), 18),
        ("CACHE", lambda row: humanize(row.get("cache_state")), 10),
        ("ERROR", lambda row: row.get("error"), None),
    )
    write_table(
        "RELAY SURFACE PROBES",
        columns,
        payload.get("probes") or [],
        stdout,
        empty="No relay surfaces were probed.",
    )


def write_relay_summary(
    payload: Mapping[str, Any],
    stdout: TextIO,
    *,
    title: str,
) -> None:
    if "supported" in payload:
        health = payload.get("relay_health")
        health = health if isinstance(health, Mapping) else {}
        fields = [
            ("Environment", payload.get("environment")),
            ("Launch agent", payload.get("launchd_label")),
            ("Supported", bool(payload.get("supported"))),
            ("Service loaded", bool(payload.get("loaded"))),
            ("Configuration present", bool(payload.get("plist_present"))),
            ("Configuration current", bool(payload.get("plist_current"))),
            ("Launch agent file", payload.get("plist_path")),
            ("State directory", payload.get("state_dir")),
            ("Report delivery", humanize(health.get("state"))),
            ("Pending reports", health.get("pending_reports")),
            ("Quarantined reports", health.get("quarantine_count")),
            ("Recovery", payload.get("relay_health_recovery")),
        ]
    else:
        claimed = payload.get("jobs")
        jobs = list(claimed) if isinstance(claimed, (list, tuple)) else []
        fields = [
            ("State", humanize(payload.get("state"))),
            ("Jobs run", len(jobs)),
            ("Error", humanize(payload.get("error_code"))),
            ("Next poll (seconds)", payload.get("next_poll_seconds")),
        ]
        for position, job in enumerate(jobs, start=1):
            fields.extend(_relay_job_fields(job, position))
    write_summary(title, fields, stdout)


def _relay_job_fields(
    job: Mapping[str, Any],
    position: int,
) -> list[tuple[str, Any]]:
    label = f"Job {position}"
    fields: list[tuple[str, Any]] = [
        (f"{label} type", humanize(job.get("job_kind"))),
        (f"{label} ID", job.get("job_id")),
        (f"{label} result", humanize(job.get("result_code"))),
        (f"{label} state", humanize(job.get("state"))),
        (f"{label} error", humanize(job.get("error_code"))),
    ]
    fields.extend(
        (f"{label} {name}", value) for name, value in native_diagnostic_fields(job)
    )
    return fields


__all__ = [
    "write_launch_result",
    "write_relay_probe_summary",
    "write_relay_summary",
]
