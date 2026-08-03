"""Pure planning for the Yoke-managed regions in Cursor's config files.

Everything here computes what a install/refresh pass *would* write and
what it owns afterwards, with no filesystem access, so the decisions stay
testable apart from the IO that applies them. :mod:`cursor_permissions`
holds the reading, writing, and reporting around these functions.

The record each plan returns is the unit of ownership the install
manifest persists: it names exactly what Yoke added to a file, so a later
uninstall removes precisely that and leaves operator content alone.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.cursor_permissions import CursorConfigRegion


def validate(region: CursorConfigRegion, managed: Any) -> Tuple[List[str], Optional[str]]:
    """Return the (entries, default) a managed region declares, or raise."""
    if not isinstance(managed, dict):
        raise ProjectInstallError(
            f"managed Cursor region for {region.rel} must be an object"
        )
    entries = managed.get("entries", [])
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) and entry for entry in entries
    ):
        raise ProjectInstallError(
            f"managed Cursor region for {region.rel} must carry 'entries' as a "
            "list of non-empty strings"
        )
    default = managed.get("default")
    if default is not None and (not isinstance(default, str) or not default):
        raise ProjectInstallError(
            f"managed Cursor region for {region.rel} must carry 'default' as a "
            "non-empty string when present"
        )
    return list(entries), default


def empty_record(**overrides: Any) -> Dict[str, Any]:
    """A record claiming nothing, with any known additions applied over it."""
    record = {
        "added_entries": [],
        "set_default": False,
        "seeded_required_list": False,
        "purged_stale_keys": [],
        "created_container": False,
        "created_file": False,
        "gated": False,
    }
    record.update(overrides)
    return record


def plan(
    region: CursorConfigRegion,
    payload: Optional[Dict[str, Any]],
    managed: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (new_payload, record) — pure, no IO. ``record`` names what we add."""
    wanted, default_wanted = validate(region, managed)
    created_file = payload is None
    container_absent = created_file or region.container not in payload
    new_payload = dict(payload) if payload else {}
    container = dict(new_payload.get(region.container) or {})
    existing = list(container.get(region.list_key) or [])
    added = [entry for entry in wanted if entry not in existing]
    resulting = existing + added
    # A region carrying a default is a policy switch: writing
    # ``default: deny`` beside an empty allow list would block every host.
    # It stays unwritten until there is at least one entry to allow.
    if region.default_key and not resulting:
        return new_payload, empty_record(gated=True)
    container[region.list_key] = resulting
    set_default = bool(
        region.default_key
        and default_wanted is not None
        and region.default_key not in container
    )
    if set_default:
        container[region.default_key] = default_wanted
    # The vendor schema requires this sibling list even when nothing is in
    # it, and rejects the whole file when it is missing. Seed it only when
    # absent, so an operator's own entries are never touched.
    seeded_required_list = bool(
        region.required_list_key and region.required_list_key not in container
    )
    if seeded_required_list:
        container[region.required_list_key] = []
    new_payload[region.container] = container
    purged = [key for key in region.stale_top_level_keys if key in new_payload]
    for key in purged:
        new_payload.pop(key)
    return new_payload, empty_record(
        added_entries=added,
        set_default=set_default,
        seeded_required_list=seeded_required_list,
        purged_stale_keys=purged,
        created_container=container_absent and (bool(added) or set_default),
        created_file=created_file,
    )


def carry_forward(record: Dict[str, Any], prior: Any) -> Dict[str, Any]:
    """Fold a prior run's record into this one.

    The manifest records what Yoke *owns* in the file, not what one run
    happened to add. Without this, a refresh — which adds nothing because
    the entries are already there — would overwrite the record with an
    empty one and uninstall would stop cleaning up what install wrote.
    """
    if not isinstance(prior, dict):
        return record
    merged = [
        entry for entry in (prior.get("added_entries") or []) if isinstance(entry, str)
    ]
    merged += [entry for entry in record["added_entries"] if entry not in merged]
    record["added_entries"] = merged
    for flag in ("set_default", "seeded_required_list", "created_container", "created_file"):
        record[flag] = bool(record[flag] or prior.get(flag))
    return record


def changed(record: Dict[str, Any]) -> bool:
    """True when this run's plan actually alters the file on disk."""
    return bool(
        record["added_entries"]
        or record["set_default"]
        or record["seeded_required_list"]
        or record["purged_stale_keys"]
        or record["created_file"]
    )


__all__ = [
    "carry_forward",
    "changed",
    "empty_record",
    "plan",
    "validate",
]
