"""Operator-facing narratives for the lane-main-write guard."""

from __future__ import annotations

from yoke_core.domain.denial_field_note_footer import append_field_note_footer

RULE_ID = "lint-lane-main-write"
SUPPRESSION_TOKEN = "# lint:no-lane-main-write-check"
ESCAPE_TOKEN = "# lint:allow-lane-main-write"


def format_denial(
    *,
    item_label: str,
    lane_path: str,
    attempted_path: str,
    lane_equivalent: str,
    mode: str,
    suppression_seen: bool,
    config_note: str = "",
) -> str:
    """Render the refusal body naming lane, attempted path, and in-lane repair."""
    config_line = f"\n{config_note}" if config_note else ""
    suffix = ""
    if mode == "warn":
        suffix = "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        suffix = (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    body = (
        "BLOCKED: source write to the main checkout while an implementation "
        "lane is held.\n\n"
        f"Held lane:     {item_label}\n"
        f"Lane path:     {lane_path}\n"
        f"Attempted:     {attempted_path}\n"
        f"Use instead:   {lane_equivalent}\n\n"
        "While this session holds an implementation-lane work claim, tracked "
        "source edits belong in the lane worktree — not the main checkout. "
        "Copy the in-lane path above into your Edit/Write/Bash call.\n\n"
        f"Deliberate main-targeted work: add `{ESCAPE_TOKEN}` to the command "
        "or tool call body (records an audit event; use only when main is "
        "intentionally the write target)."
        f"{config_line}{suffix}"
    )
    return append_field_note_footer(body, rule_id=RULE_ID)


def format_stranded_advisory(*, item_label: str, lane_path: str) -> str:
    """Advisory when a held lane claim's worktree is gone from disk."""
    return (
        f"ADVISORY: implementation-lane claim {item_label} is held but its "
        f"recorded worktree is missing on disk ({lane_path}). "
        "lane-main-write is not armed — a gone lane cannot be the write "
        "target. Release or re-prepare the lane if the claim is stale."
    )


__all__ = [
    "ESCAPE_TOKEN",
    "RULE_ID",
    "SUPPRESSION_TOKEN",
    "format_denial",
    "format_stranded_advisory",
]
