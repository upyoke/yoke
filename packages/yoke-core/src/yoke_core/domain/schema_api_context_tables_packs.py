"""Pack projection entries for the agent-facing schema packet."""

from __future__ import annotations


PACK_TABLES: dict[str, dict] = {
    "pack_catalog": {
        "columns": [
            ("slug", "TEXT"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("latest_version", "TEXT"),
            ("dependencies_json", "TEXT"),
            ("documentation", "TEXT"),
            ("file_count", "INTEGER"),
            ("observed_at", "TEXT"),
        ],
        "notes": (
            "Server-shipped Pack catalog projected for UI and search. The "
            "plain-language Pack label is `name`; there is NO `display_name` "
            "column (stale guess). `description` is the user-facing explanation, "
            "and `latest_version` names the newest immutable Pack version. "
            "Repository receipts, not this table, are installation authority."
        ),
    },
    "project_pack_reports": {
        "columns": [
            ("project_id", "INTEGER"),
            ("receipt_digest", "TEXT"),
            ("pack_count", "INTEGER"),
            ("reported_at", "TEXT"),
        ],
        "notes": (
            "One timestamped Pack receipt report per project. `project_id` is "
            "both the primary key and the join to `projects.id`; `reported_at` "
            "drives fresh/stale UI labeling. The report is a projection of the "
            "project's `.yoke/packs.json`, never a replacement for it."
        ),
    },
    "project_pack_report_entries": {
        "columns": [
            ("project_id", "INTEGER"),
            ("pack_slug", "TEXT"),
            ("installed_version", "TEXT"),
            ("file_count", "INTEGER"),
        ],
        "notes": (
            "Installed Pack rows from the project's latest report, keyed by "
            "`(project_id, pack_slug)`. `installed_version` is the last-applied "
            "immutable version; it does not claim ownership of project files or "
            "turn later customization into drift."
        ),
    },
}


__all__ = ["PACK_TABLES"]
