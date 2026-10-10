"""Argument registration for capability settings commands."""

from typing import Any


def register_capability_settings_parsers(sub: Any) -> None:
    """Register the three subcommand parsers on the parent's subparser action."""
    p = sub.add_parser(
        "capability-get-settings",
        help=(
            "Get non-sensitive settings JSON (the printed text is the CAS "
            "base token for capability-set-settings)"
        ),
        description=(
            "Print the settings document for one capability. The exact "
            "printed text is the compare-and-swap base token for a "
            "full-document write: get -> edit -> capability-set-settings "
            "--base '<as-read-text>'. Exit 1 (no row) means create via "
            "capability-set-settings --new. Single-key updates skip the "
            "cycle via capability-merge-settings."
        ),
    )
    p.add_argument("project")
    p.add_argument("type")
    p = sub.add_parser(
        "capability-set-settings",
        help=(
            "CAS-write settings JSON (requires --base, the as-read text "
            "from capability-get-settings, or --new to create)"
        ),
        description=(
            "Full-document write, compare-and-swap protected: pass the "
            "exact text capability-get-settings printed as --base, or "
            "--new when the get exited 1 (no row yet). A stale base or a "
            "lost create race refuses with settings_conflict instead of "
            "silently erasing the newer write. Prefer "
            "capability-merge-settings for single-key updates."
        ),
    )
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument("settings_json")
    p.add_argument(
        "--base",
        dest="base_settings_json",
        default=None,
        metavar="AS_READ_JSON",
        help=(
            "The exact settings text read via capability-get-settings; "
            "the write lands only while the stored text still equals it."
        ),
    )
    p.add_argument(
        "--new",
        dest="create",
        action="store_true",
        help=(
            "Insert-only create for a capability the get reported "
            "absent; refuses if the row appeared meanwhile."
        ),
    )
    p = sub.add_parser(
        "capability-merge-settings",
        help=(
            "Merge key.path=value assignments into capability settings "
            "(read-merge-CAS with one retry; creates absent rows)"
        ),
        description=(
            "Set individual keys without replacing the whole document: "
            "reads the current settings (absent rows start from {}), "
            "applies each --set key.path=value (value parsed as JSON when "
            "possible, raw string otherwise), and CAS-writes with one "
            "retry on conflict."
        ),
    )
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument(
        "--set",
        dest="assignments",
        action="append",
        required=True,
        metavar="KEY.PATH=VALUE",
        help="Assignment to merge; repeatable.",
    )
    p = sub.add_parser(
        "capability-remove-settings",
        help="Remove one capability only while its settings match --base",
    )
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument("--base", dest="base_settings_json", required=True)
