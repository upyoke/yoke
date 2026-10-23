"""Remove an explicitly selected checkout mapping when installation never wrote a layer."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.machine_config import schema as contract
from yoke_cli.config import machine_config_file
from yoke_cli.config.machine_config_mutation import load_payload, serialized_mutation
from yoke_cli.project_install import owned_cleanup, uninstall_commit
from yoke_cli.project_install.files import MODE_COPY, MODE_KEY, ProjectInstallError
from yoke_cli.project_install.source_dev import (
    is_yoke_source_checkout,
    source_link_uninstall_refusal,
)


@serialized_mutation
def uninstall_registration(root: Path, *, path=None) -> dict:
    """Explicit uninstall owns only the exact selected registration, never unrecorded files."""
    if is_yoke_source_checkout(root):
        raise source_link_uninstall_refusal(root)
    payload, cfg = load_payload(path)
    entries = contract.projects_for_connection(payload)
    exact = [entry for entry in entries if Path(entry["checkout"]).resolve() == root]
    if len(exact) != 1:
        raise ProjectInstallError(
            f"project_uninstall_registration_missing: {root} has no exact checkout "
            "registration or install manifest on this connection. Select the "
            "owning connection and registered checkout, then retry project uninstall."
        )
    # Existing uninstall guards cover both untracked work and a dirty index.
    _, warnings = uninstall_commit.prepare(
        root, {"project_id": exact[0]["project_id"]}, cfg
    )
    if (root / ".yoke").exists() or (root / ".yoke").is_symlink():
        raise ProjectInstallError(
            "project_uninstall_manifest_missing: .yoke exists without its install "
            "manifest. Preserve its contents and recover the install manifest, "
            "then retry project uninstall; no registration or file was removed."
        )
    reason = owned_cleanup.scope_reason(
        root, {"project_id": exact[0]["project_id"]}, cfg
    )
    if reason:
        raise ProjectInstallError(
            f"project_uninstall_{reason}: checkout registration has unresolved "
            "sharing or identity. Separate shared checkouts or repair the named "
            "mapping, then retry project uninstall; nothing was removed."
        )
    connection = contract.project_connection(payload)
    # Keep raw bytes' values for every other entry, namespace and setting.
    group = payload["connection_projects"][connection]
    group[:] = [entry for entry in group if Path(entry["checkout"]).resolve() != root]
    machine_config_file.atomic_write_text(cfg, json.dumps(payload, indent=2) + "\n")
    return {
        "operation": "uninstall",
        MODE_KEY: MODE_COPY,
        "repo_root": str(root),
        "outcome": "complete",
        "manifest_removed": False,
        "files_removed": [],
        "warnings": warnings,
        "local_cleanup": {
            "complete": True,
            "registration": {
                "status": "removed",
                "reason": "exact_registered_checkout",
            },
            "trust": [],
        },
        "commit": {"status": "not_needed"},
    }
