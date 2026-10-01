"""Human-readable native relay service and build status fields."""

from __future__ import annotations
from typing import Any, Mapping
from yoke_cli.commands.adapters.session_control_human_output import humanize


def relay_status_fields(payload: Mapping[str, Any]) -> list[tuple[str, Any]]:
    health = payload.get("relay_health")
    health = health if isinstance(health, Mapping) else {}
    poll = health.get("poll_outcome")
    poll = poll if isinstance(poll, Mapping) else {}
    fields = [
        ("Environment", payload.get("environment")),
        ("User service", payload.get("unit_name") or payload.get("launchd_label")),
        ("Supported", bool(payload.get("supported"))),
        ("Service loaded", bool(payload.get("loaded"))),
        (
            "Configuration present",
            bool(payload.get("unit_present", payload.get("plist_present"))),
        ),
        (
            "Configuration current",
            bool(payload.get("unit_current", payload.get("plist_current"))),
        ),
        ("Service file", payload.get("unit_path") or payload.get("plist_path")),
        ("State directory", payload.get("state_dir")),
        ("Pinned relay release", payload.get("pinned_release")),
        ("Served build", payload.get("served_build")),
        ("Release pin current", bool(payload.get("release_current"))),
        ("Distribution index", payload.get("distribution_index")),
        ("Release pin error", payload.get("release_error_code")),
        ("Release pin recovery", payload.get("release_recovery")),
        ("Report delivery", humanize(health.get("state"))),
        ("Control-plane poll", humanize(poll.get("status"))),
        ("Poll error", poll.get("error_code")),
        ("Poll consecutive failures", poll.get("consecutive_failures")),
        ("Last successful poll", poll.get("last_succeeded_at")),
        ("Last failed poll", poll.get("last_failed_at")),
        ("Pending reports", health.get("pending_reports")),
        ("Quarantined reports", health.get("quarantine_count")),
        ("Recovery", payload.get("relay_health_recovery")),
    ]
    if "unit_name" in payload:
        fields.extend(
            [
                ("Enabled at login", payload.get("enabled")),
                ("Supervision reason", payload.get("supervision_reason")),
                ("Logout behavior", payload.get("logout_behavior")),
            ]
        )
    return fields
