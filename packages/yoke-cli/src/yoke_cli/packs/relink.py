"""Preview-first relinking of project-moved files in an installed Pack."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from yoke_cli.packs.errors import PackClientError
from yoke_cli.packs.merge import file_state
from yoke_cli.packs.receipt import (
    assert_pack_targets_safe,
    load_receipt,
    write_receipt,
)
from yoke_cli.packs.runner_support import (
    _assert_checkout_project,
    _fetch_bundle,
    _report_receipt,
)
from yoke_contracts.packs import PACK_RECEIPT_REL


def run_pack_relink(
    repo_root: str | Path | None,
    *,
    project: str,
    pack: str,
    from_path: str,
    to_path: str,
    apply: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Point one existing Pack file identity at its new project location."""
    root = Path(repo_root or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise PackClientError(f"project checkout is not a directory: {root}")
    receipt = load_receipt(root)
    if receipt is None:
        raise PackClientError("Pack relink requires an existing .yoke/packs.json")
    record = receipt["packs"].get(pack)
    if record is None:
        raise PackClientError(f"Pack {pack!r} is not installed")

    bundle = _fetch_bundle(
        project,
        pack,
        version=record["version"],
        render_values=record["render_values"],
        session_id=session_id,
    )
    _assert_checkout_project(root, bundle, receipt)
    assert_pack_targets_safe(root, [from_path, to_path])

    matches = [
        (pack_path, file_record)
        for pack_path, file_record in record["files"].items()
        if file_record["path"] == from_path
    ]
    if not matches:
        raise PackClientError(
            f"Pack {pack!r} does not currently record project path {from_path!r}"
        )
    if (root / from_path).exists():
        raise PackClientError(
            f"original project path still exists: {from_path!r}; move or remove it "
            "before relinking"
        )
    destination = file_state(root / to_path)
    if destination is None:
        raise PackClientError(f"new project path does not exist: {to_path!r}")

    claimed = {
        file_record["path"]: (slug, pack_path)
        for slug, installed in receipt["packs"].items()
        for pack_path, file_record in installed["files"].items()
        if file_record["path"] != from_path
    }
    if to_path in claimed:
        owner, owner_path = claimed[to_path]
        raise PackClientError(
            f"new project path {to_path!r} is already linked to "
            f"Pack {owner!r} file {owner_path!r}"
        )

    pack_path, baseline = matches[0]
    baseline_match = (
        destination["sha256"] == baseline["sha256"]
        and destination["mode"] == baseline["mode"]
    )
    report: dict[str, Any] = {
        "operation": "relink",
        "project_id": receipt["project_id"],
        "project_slug": receipt["project_slug"],
        "repo_root": str(root),
        "pack": pack,
        "pack_path": pack_path,
        "from_path": from_path,
        "to_path": to_path,
        "destination_matches_baseline": baseline_match,
        "destination_is_customized": not baseline_match,
        "applied": False,
        "receipt": str(root / PACK_RECEIPT_REL),
    }
    if not apply:
        return report

    updated = json.loads(json.dumps(receipt))
    updated["packs"][pack]["files"][pack_path]["path"] = to_path
    write_receipt(root, updated)
    report["applied"] = True
    try:
        report["projection"] = _report_receipt(project, updated, session_id=session_id)
    except PackClientError as exc:
        report["projection"] = None
        report["projection_warning"] = str(exc)
    return report


__all__ = ["run_pack_relink"]
