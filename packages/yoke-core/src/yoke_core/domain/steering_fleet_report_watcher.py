"""Compact digest and disappearance inputs for the fleet watcher."""

from yoke_core.domain.fleet_delta_disappearances import ROW_SECTIONS
from yoke_core.domain.steering_fleet_report_hook_digest import combined_hook_digest
from yoke_core.domain.steering_fleet_report_projection import report_dict


# These are the only cells read by shown_rows/disappeared_lines. Keep the
# complete identity set: the displayed cap and current-cause check differ.
ROW_FIELDS = frozenset(
    {
        "session_id",
        "holder_session_id",
        "item_id",
        "public_ref",
        "run_id",
        "custody_run_id",
        "parked",
        "idle_seconds",
        "merged",
        "closed",
        "pr_number",
        "narrative",
    }
)


def watcher_dict(combined):
    scopes = []
    for section in combined.sections:
        report = report_dict(section.report)
        scopes.append(
            {
                "descriptor": section.descriptor,
                "project_id": section.report.project_id,
                "idle_after_seconds": section.report.idle_after_seconds,
                **{
                    key: [
                        {
                            field: value
                            for field, value in row.items()
                            if field in ROW_FIELDS
                        }
                        for row in report[key]
                    ]
                    for key in (*ROW_SECTIONS, "holders")
                },
            }
        )
    return {
        "composed_at": combined.composed_at,
        "actionable": combined.actionable,
        "fingerprint": combined.fingerprint(),
        "digest": combined_hook_digest(combined),
        "slow_paths": [row.to_dict() for row in combined.slow_paths],
        "scopes": scopes,
    }
