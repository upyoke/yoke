"""Human output for fleet launch records and machine-relay state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TextIO

from yoke_cli.commands.adapters.session_control_human_output import (
    Column,
    EMPTY_VALUE,
    humanize,
    utc_time,
    write_summary,
    write_table,
)


def _launch_status(launch: Mapping[str, Any]) -> str:
    state = humanize(launch.get("state"))
    result = humanize(launch.get("result_code"))
    return f"{state} ({result})" if result != EMPTY_VALUE else state


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
        ("Model", launch.get("requested_model")),
        ("Fallback allowed", bool(launch.get("allow_surface_fallback"))),
        ("Registered session", launch.get("registered_session_id")),
        ("Created (UTC)", utc_time(launch.get("created_at"))),
        ("Deadline (UTC)", utc_time(launch.get("deadline_at"))),
        ("Completed (UTC)", utc_time(launch.get("completed_at"))),
    ]
    if deduplicated is not None:
        fields.insert(2, ("Deduplicated", bool(deduplicated)))
    write_summary("LAUNCH", fields, stdout)


def _write_launch_preview(result: Mapping[str, Any], stdout: TextIO) -> None:
    selected = result.get("selected_relay")
    selected_row = selected if isinstance(selected, Mapping) else {}
    requested_model = result.get("requested_model")
    write_summary(
        "LAUNCH PREVIEW",
        [
            ("Outcome", humanize(result.get("outcome"))),
            ("Requested surface", result.get("requested_surface")),
            ("Requested model", requested_model),
            (
                "Model verification",
                "at session registration" if requested_model else "not requested",
            ),
            ("Selected surface", result.get("selected_surface")),
            ("Fallback used", bool(result.get("fallback_used"))),
            ("Launchable", bool(result.get("launchable"))),
            ("Selected relay", selected_row.get("relay_id")),
            ("Selected machine", selected_row.get("machine_id")),
        ],
        stdout,
    )
    columns: tuple[Column, ...] = (
        ("RELAY", lambda row: row.get("relay_id"), 24),
        ("MACHINE", lambda row: row.get("machine_id"), None),
        ("SURFACE", lambda row: row.get("surface"), 20),
        ("VERSION", lambda row: row.get("version"), 18),
        ("LAST SEEN (UTC)", lambda row: utc_time(row.get("last_seen_at")), 22),
    )
    write_table(
        "ELIGIBLE RELAYS",
        columns,
        result.get("eligible_relays") or [],
        stdout,
        empty="No eligible relays found.",
    )


def write_launch_result(result: Mapping[str, Any], stdout: TextIO) -> None:
    if "launches" in result:
        columns: tuple[Column, ...] = (
            ("LAUNCH", lambda row: row.get("launch_id"), None),
            ("STATE / RESULT", _launch_status, 28),
            ("PROJECT", lambda row: row.get("project") or row.get("project_id"), 14),
            ("REQUESTED", lambda row: row.get("requested_surface"), 18),
            ("SELECTED", lambda row: row.get("selected_surface"), 18),
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
        _write_launch_preview(result, stdout)
        return
    print("LAUNCH\nNo launch details returned.", file=stdout)


def write_relay_summary(
    payload: Mapping[str, Any],
    stdout: TextIO,
    *,
    title: str,
) -> None:
    if "supported" in payload:
        fields = [
            ("Environment", payload.get("environment")),
            ("Launch agent", payload.get("launchd_label")),
            ("Supported", bool(payload.get("supported"))),
            ("Service loaded", bool(payload.get("loaded"))),
            ("Configuration present", bool(payload.get("plist_present"))),
            ("Configuration current", bool(payload.get("plist_current"))),
            ("Launch agent file", payload.get("plist_path")),
            ("State directory", payload.get("state_dir")),
        ]
    else:
        fields = [
            ("State", humanize(payload.get("state"))),
            ("Job type", humanize(payload.get("job_kind"))),
            ("Job ID", payload.get("job_id")),
            ("Result", humanize(payload.get("result_code"))),
            ("Error", humanize(payload.get("error_code"))),
            ("Next poll (seconds)", payload.get("next_poll_seconds")),
        ]
    write_summary(title, fields, stdout)


__all__ = ["write_launch_result", "write_relay_summary"]
