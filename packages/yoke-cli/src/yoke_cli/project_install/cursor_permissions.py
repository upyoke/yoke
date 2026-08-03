"""Yoke-managed regions inside ``.cursor/cli.json`` and ``.cursor/sandbox.json``.

The bundle's Cursor hook subtree flows through :mod:`hooks`; this module
owns the two sibling gates that decide whether a Cursor session can run
Yoke commands at all — command approvals in ``cli.json`` and the network
allow list in ``sandbox.json``. Without them a Cursor session prompts on
(or fails) every network-touching ``yoke`` call even when the hook chain
loads perfectly.

Region content comes from :mod:`yoke_contracts.cursor_permissions` rather
than from the bundle, because the network origins name whichever control
plane and GitHub endpoint the *installing machine* is configured against
— a server-built bundle cannot know them. What a pass would write, and
what it owns afterwards, is computed in
:mod:`yoke_cli.project_install.cursor_permissions_plan`; this module
reads, writes, and reports around those decisions.

The contract matches the Claude permissions region: manage exactly our
region, never the operator's keys.

* the region's list — union in the entries Yoke requires; operator
  entries are never removed or reordered, and refresh is idempotent.
* the region's default scalar — seed only when the key is absent; an
  operator's explicit choice is never overwritten.

The install manifest records exactly what this pass added, per file, so
uninstall removes precisely that and nothing an operator authored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_cli.project_install.cursor_permissions_plan import (
    carry_forward as _carry_forward,
    changed as _changed,
    plan as _plan,
)
from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
    remove_empty_parents,
)
from yoke_contracts.cursor_permissions import (
    CURSOR_CONFIG_REGIONS,
    CURSOR_CONFIG_RELS,
    CURSOR_PERMISSIONS_MANIFEST_KEY,
    CursorConfigRegion,
    managed_cursor_regions,
)

# Manifest key holding the per-file records this pass writes.
MANIFEST_KEY = CURSOR_PERMISSIONS_MANIFEST_KEY


def _load(target: Path) -> Optional[Dict[str, Any]]:
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectInstallError(
            f"{target} is not valid JSON ({exc}); repair it before rerunning "
            "`yoke project install`"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectInstallError(f"{target} must contain a JSON object")
    return payload


def _write(target: Path, payload: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _region_plans(
    repo_root: Path, config: Optional[Dict[str, Any]] = None,
) -> List[Tuple[CursorConfigRegion, Path, Dict[str, Any], Dict[str, Any]]]:
    """Plan every managed region without writing; shared by apply/preview.

    Each entry is ``(region, target, new_payload, record)``.
    """
    assert_resolved_targets_within(
        repo_root,
        CURSOR_CONFIG_RELS,
        context="Cursor permission region mutation",
    )
    managed_by_rel = managed_cursor_regions(config)
    plans = []
    for region in CURSOR_CONFIG_REGIONS:
        target = repo_root / region.rel
        new_payload, record = _plan(
            region, _load(target), managed_by_rel[region.rel],
        )
        plans.append((region, target, new_payload, record))
    return plans


def _summary(region: CursorConfigRegion, record: Dict[str, Any]) -> str:
    bits: List[str] = []
    if record["added_entries"]:
        bits.append(f"allowed {len(record['added_entries'])} entry(s)")
    if record["set_default"]:
        bits.append(f"set {region.container}.{region.default_key}")
    if record["seeded_required_list"]:
        bits.append(f"seeded {region.container}.{region.required_list_key}")
    if record["purged_stale_keys"]:
        bits.append(f"purged {', '.join(record['purged_stale_keys'])}")
    return ", ".join(bits) or "managed region"


def _unchanged_action(
    region: CursorConfigRegion, record: Dict[str, Any], *, planned: bool = False,
) -> str:
    if record["gated"]:
        verb = "Would skip" if planned else "Skipped"
        return (
            f"{verb}: {region.rel} (this machine declares no control-plane "
            "origin to allow; a deny-all policy would block every host)"
        )
    verb = "Would keep" if planned else "Exists"
    return f"{verb}: {region.rel} (Yoke Cursor policy up to date)"


def apply_cursor_permissions(
    repo_root: Path,
    *,
    prior_records: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Union Yoke's regions into the Cursor config files.

    Returns ``(records, report)``. ``records`` (manifest-persisted, keyed by
    repo-relative path) names everything Yoke owns in each file — this run's
    additions folded into ``prior_records`` — so uninstall stays precise
    across refreshes that add nothing new.
    """
    records: Dict[str, Any] = {}
    actions: List[str] = []
    changed_any = False
    prior = prior_records if isinstance(prior_records, dict) else {}
    for region, target, new_payload, record in _region_plans(repo_root, config):
        # Judge the write from THIS run's plan, then fold history into the
        # record — carrying a prior ``created_file`` forward would otherwise
        # make every refresh look like a change and rewrite the file.
        changed = _changed(record)
        records[region.rel] = _carry_forward(record, prior.get(region.rel))
        if changed:
            _write(target, new_payload)
            changed_any = True
            actions.append(
                f"Updated: {region.rel} ({_summary(region, record)}; "
                "your other settings preserved)"
            )
        else:
            actions.append(_unchanged_action(region, record))
    return records, {"actions": actions, "changed": changed_any}


def preview_cursor_permissions(
    repo_root: Path, *, config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan the Cursor region mutations without writing (review/preview)."""
    actions: List[str] = []
    would_change = False
    for region, _target, _new_payload, record in _region_plans(repo_root, config):
        if _changed(record):
            would_change = True
            actions.append(
                f"Would update: {region.rel} ({_summary(region, record)}; "
                "your other settings preserved)"
            )
        else:
            actions.append(_unchanged_action(region, record, planned=True))
    return {"actions": actions, "would_change": would_change}


def remove_cursor_permissions(
    repo_root: Path, records: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Uninstall pass: remove exactly the entries and defaults we added.

    Deletes a file only when this pass created it and nothing else remains,
    so an operator-authored Cursor config always survives.
    """
    if not records:
        return {"removed_entries": {}, "deleted_files": []}
    assert_resolved_targets_within(
        repo_root,
        CURSOR_CONFIG_RELS,
        context="Cursor permission region removal",
    )
    removed_by_rel: Dict[str, List[str]] = {}
    deleted: List[str] = []
    for region in CURSOR_CONFIG_REGIONS:
        record = records.get(region.rel)
        if not isinstance(record, dict):
            continue
        target = repo_root / region.rel
        payload = _load(target)
        if payload is None:
            continue
        removed = _strip_region(region, payload, record)
        if removed:
            removed_by_rel[region.rel] = removed
        if record.get("created_file") and not payload:
            target.unlink()
            remove_empty_parents(repo_root, region.rel)
            deleted.append(region.rel)
        elif removed or record.get("set_default"):
            _write(target, payload)
    return {"removed_entries": removed_by_rel, "deleted_files": deleted}


def _strip_region(
    region: CursorConfigRegion, payload: Dict[str, Any], record: Dict[str, Any],
) -> List[str]:
    """Remove our entries/default from *payload* in place; return what went."""
    added = list(record.get("added_entries") or [])
    container = payload.get(region.container)
    removed: List[str] = []
    if isinstance(container, dict) and isinstance(container.get(region.list_key), list):
        current = container[region.list_key]
        removed = [entry for entry in current if entry in added]
        kept = [entry for entry in current if entry not in added]
        if kept:
            container[region.list_key] = kept
        else:
            container.pop(region.list_key, None)
    if isinstance(container, dict) and record.get("set_default") and region.default_key:
        container.pop(region.default_key, None)
    # Only reclaim the seeded list while it is still the empty one we wrote;
    # an operator who has since denied something owns it now.
    if (
        isinstance(container, dict)
        and record.get("seeded_required_list")
        and region.required_list_key
        and container.get(region.required_list_key) == []
    ):
        container.pop(region.required_list_key, None)
    if isinstance(container, dict):
        if record.get("created_container") and not container:
            payload.pop(region.container, None)
        else:
            payload[region.container] = container
    return removed


__all__ = [
    "MANIFEST_KEY",
    "apply_cursor_permissions",
    "preview_cursor_permissions",
    "remove_cursor_permissions",
]
