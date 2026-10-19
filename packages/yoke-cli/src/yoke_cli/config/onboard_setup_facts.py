"""Secret-free setup observations from the requesting machine."""

from __future__ import annotations

import json
import os
from importlib.metadata import version
from pathlib import Path
from typing import Any

from yoke_cli.config import machine_config
from yoke_cli.packs.receipt import PackReceiptError, load_receipt
from yoke_contracts.machine_config.schema import MachineConfigContractError
from yoke_contracts.machine_config.runtime import (
    machine_id,
    MachineConfigError as MachineIdentityError,
)
from yoke_contracts.onboard_checklist import STATUS_CONFIGURED, STATUS_UNKNOWN


def collect(
    *,
    config_path: str | Path | None = None,
    checkout_path: str | Path | None = None,
    project_id: int | None = None,
    machine_only: bool = False,
) -> dict[str, Any]:
    # Project installation imports the onboarding dispatcher during bootstrap.
    from yoke_cli.project_install.files import ProjectInstallError, load_manifest

    selected = machine_config.config_path(config_path)
    try:
        identity = machine_id(selected)
        if not identity:
            return {"machine_id": None, "observations": {}}
        connection = machine_config.product_connection(
            selected,
            explicit_env=os.environ.get("YOKE_ENV") or None,
        )
    except (
        OSError,
        ValueError,
        machine_config.MachineConfigError,
        MachineIdentityError,
        MachineConfigContractError,
    ) as exc:
        raise ValueError(
            "setup_machine_config_unreadable: repair this machine's config with yoke setup."
        ) from exc
    observations = {
        "package-install": _fact(True, "running-cli", version("yoke-cli")),
        "machine-profile": _fact(True, "machine-config"),
        "yoke-connection": _fact(bool(connection), "active-product-connection"),
    }
    if machine_only:
        return {"machine_id": identity, "observations": observations}
    root = Path(checkout_path or Path.cwd()).expanduser().resolve()
    try:
        entry = machine_config.project_entry(root, selected)
        bound_id = entry.get("project_id")
        matches = bound_id is not None and (
            project_id is None or bound_id == project_id
        )
        binding = _fact(matches and root.is_dir(), "machine-checkout-binding")
        binding["evidence"]["project_id"] = bound_id
        binding["evidence"]["checkout_path"] = str(root)
        observations["checkout-binding"] = binding
        manifest = load_manifest(root)
        installed = bool(manifest) and manifest.get("project_id") == bound_id
        observations["deterministic-repo-substrate"] = _fact(
            matches and installed,
            "project-install-manifest",
        )
        receipt = load_receipt(root)
        scaffold = (
            bool(receipt)
            and receipt.get("project_id") == bound_id
            and ("webapp-scaffold" in receipt.get("packs", {}))
        )
        observations["scaffold-install"] = _fact(matches and scaffold, "pack-receipt")
        github = machine_config.github_config(selected)
        observations["machine-github-connection"] = _fact(
            bool(github.get("authorization")),
            "machine-github-configuration",
        )
    except (OSError, ValueError, ProjectInstallError, PackReceiptError) as exc:
        raise ValueError(
            "setup_checkout_unreadable: repair the checkout's installed guidance "
            "or Pack receipt, then reread yoke onboard checklist."
        ) from exc
    return {"machine_id": identity, "observations": observations}


def _fact(
    present: bool, source: str, installed_version: str | None = None
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"source": source, "present": present}
    if installed_version:
        evidence["version"] = installed_version
    return {
        "status": STATUS_CONFIGURED if present else STATUS_UNKNOWN,
        "evidence": evidence,
        "reason": "" if present else "machine_prerequisite_missing",
        "recovery": ""
        if present
        else "Run yoke setup on this machine, then resume the checklist.",
    }


def read_profile(path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).expanduser().read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(
            "setup_profile_unreadable: supply a readable confirmed profile JSON file."
        ) from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError(
            "setup_profile_invalid: provide a nonempty confirmed profile object."
        )
    return payload
