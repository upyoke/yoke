"""Retire only machine-local state proved exclusive to this installed checkout."""

from __future__ import annotations

from yoke_contracts.project_contract.install_error import ProjectInstallError
from pathlib import Path
import subprocess
import json

from yoke_contracts.harness_folder_trust_revert import revert_folder_trust
from yoke_contracts.harness_folder_trust import cursor_trust_file
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.machine_config.schema_projects import normalize_projects
from yoke_contracts.machine_config.settings_keys import MACHINE_SETTING_KEYS
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import machine_config_file
from yoke_cli.config.machine_config_mutation import (
    load_payload,
    serialized_mutation,
)
from yoke_cli.project_install import files

REGISTRATION_KEY = "local_registration"


def scope_reason(root: Path, manifest: dict, config_path) -> str:
    """Check shared Git-hook scope before any installed files are removed."""
    try:
        payload = machine_config.load_config(config_path)
        projects = [
            entry
            for entries in contract.connection_project_maps(payload).values()
            for entry in normalize_projects(entries)
        ]
        return _config_reason(
            manifest, machine_config.config_path(config_path)
        ) or _shared_reason(root, projects, manifest.get("project_id"))
    except (OSError, ValueError, RuntimeError, TypeError, subprocess.SubprocessError):
        return "checkout_scope_unavailable"


def _registration_intent(root: Path) -> Path | None:
    """Machine-local proof, in Git's metadata, that an install wrote the mapping."""
    from yoke_cli.project_install import checkout_gate

    if not checkout_gate.is_git_checkout(root):
        return None
    found = checkout_gate.run_git(
        root, "rev-parse", "--git-path", "yoke-install-registration", encoding="utf-8"
    )
    if found.returncode or not found.stdout.strip():
        raise ProjectInstallError(
            f"registration_intent_unavailable: Git could not locate metadata for {root}; "
            "repair the Git worktree, then rerun yoke project install"
        )
    path = Path(found.stdout.strip())
    return path if path.is_absolute() else root / path


def intend_registration(root: Path, config_path) -> None:
    """Record ownership BEFORE writing the mapping, so a kill cannot lose it."""
    path = _registration_intent(root)
    if path is not None:
        try:
            path.write_text(
                str(machine_config.config_path(config_path).resolve()), encoding="utf-8"
            )
        except OSError as exc:
            raise ProjectInstallError(
                f"registration_intent_unwritable: {path}: {exc}; "
                "repair the Git worktree metadata or permissions, then rerun yoke project install"
            ) from exc


def registration_intended(root: Path, config_path) -> bool:
    """Whether an interrupted install of this checkout wrote its mapping."""
    path = _registration_intent(root)
    return (
        path is not None
        and path.is_file()
        and path.read_text(encoding="utf-8")
        == str(machine_config.config_path(config_path).resolve())
    )


def record_registration(root: Path, project_id: int, config_path) -> None:
    """Attach the exact mapping introduced by this install to its manifest."""
    payload = machine_config.load_config(config_path)
    checkout = main_checkout(root).resolve()
    matching = [entry for entry in contract.projects_for_connection(payload)
                if Path(entry["checkout"]).expanduser().resolve() == checkout
                and entry["project_id"] == project_id]
    if len(matching) != 1:
        raise ProjectInstallError(
            "registration_ownership_unproven: expected one exact checkout/project mapping"
        )
    manifest = files.load_manifest(root)
    manifest[REGISTRATION_KEY] = {
        "config": str(machine_config.config_path(config_path).resolve()),
        "connection": contract.project_connection(payload),
        "entry": dict(matching[0]),
    }
    files.write_manifest(root, manifest)
    intent = _registration_intent(root)
    if intent is not None:
        intent.unlink(missing_ok=True)


def refresh_registration_policy(root, config_path, connection, previous, updated) -> None:
    """Carry established ownership through a serialized publication-only change."""
    if previous == updated:
        return
    checkout = main_checkout(Path(root)).resolve()
    manifest = files.load_manifest(checkout)
    record = manifest.get(REGISTRATION_KEY) if manifest else None
    if (
        not isinstance(record, dict)
        or record.get("config") != str(Path(config_path).resolve())
        or record.get("connection") != connection
        or record.get("entry") != previous
        or previous.get("project_id") != manifest.get("project_id")
        or Path(previous["checkout"]).expanduser().resolve() != checkout
        or updated != {**previous, "publication_read_only": updated.get("publication_read_only")}
        or type(updated.get("publication_read_only")) is not bool
    ):
        return
    record["entry"] = dict(updated)
    try:
        files.write_manifest(checkout, manifest)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ProjectInstallError(
            "registration_policy_receipt_failed: publication setting changed but its "
            "ownership receipt could not be saved; preserve the mapping and review "
            "the install manifest before uninstalling"
        ) from exc


def cleanup(root: Path, manifest: dict, config_path) -> dict:
    """Keep independent failures reviewable without claiming complete retirement."""
    try:
        return _cleanup(root, manifest, path=config_path)
    except (
        OSError,
        ValueError,
        RuntimeError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        return {
            "complete": False,
            "trust": [],
            "registration": _result("failed", "local_cleanup_unavailable", str(exc)),
        }


def lanes_dir(root: Path, payload: dict) -> Path:
    """The checkout's linked-worktree directory, as lane provisioning names it."""
    settings = payload.get("settings") if isinstance(payload, dict) else None
    configured = settings.get("worktrees_dir") if isinstance(settings, dict) else None
    return root / str(configured or MACHINE_SETTING_KEYS["worktrees_dir"].default)


@serialized_mutation
def _cleanup(root: Path, manifest: dict, *, path=None) -> dict:
    payload, cfg = load_payload(path)
    groups = contract.connection_project_maps(payload)
    owners = owning_connections(payload, root)
    connection = registration_connection(payload, owners)
    projects = normalize_projects(groups.get(connection))
    all_projects = [
        entry for entries in groups.values() for entry in normalize_projects(entries)
    ]
    reason = (
        ("checkout_shared_with_other_connection" if len(owners) > 1 else "")
        or _config_reason(manifest, cfg)
        or _shared_reason(root, all_projects, manifest.get("project_id"))
    )
    lane_cleanup = []
    if not reason:
        from yoke_contracts.harness_lane_cleanup import cleanup_lane_configs

        receipt = cleanup_lane_configs(managed_roots=(lanes_dir(root, payload),))
        lane_cleanup = [
            dict(
                harness=row["harness"],
                status="failed" if "error" in row else "removed",
                reason=row.get("error", "retired_lane_path_state"),
                checkout=str(root),
                detail=row.get("detail", ""),
                recovery=row.get("recovery", ""),
            )
            for row in receipt["files"]
        ]
    trust = (
        revert_folder_trust(
            root, exclusive_reason=reason, lanes_dir=lanes_dir(root, payload)
        )
        + lane_cleanup
    )
    record = manifest.get(REGISTRATION_KEY)
    exact = [
        entry
        for entry, normalized in zip(
            groups.get(connection, []),
            projects,
            strict=True,
        )
        if Path(normalized["checkout"]).expanduser().resolve() == root
    ]
    if reason:
        registration = _result("preserved", reason)
    elif not exact:
        registration = _result("absent", "no_exact_registration")
    elif not isinstance(record, dict) or record.get("config") != str(cfg.resolve()):
        registration = _result(
            "preserved",
            "registration_ownership_unknown",
            recovery=(
                "This install did not write the checkout mapping (`yoke project "
                "register` or an install before ownership was recorded did), so "
                f"it stays. If nothing else uses it, delete the {root} entry under "
                f"connection_projects.{connection} in {cfg}, then rerun project "
                "uninstall."
            ),
        )
    elif (
        len(exact) != 1
        or record.get("connection") != connection
        or exact[0] != record.get("entry")
        or exact[0].get("project_id") != manifest.get("project_id")
    ):
        registration = _result("preserved", "registration_modified")
    elif any(row["status"] == "failed" for row in trust):
        registration = _result("preserved", "trust_cleanup_unresolved")
    else:
        groups[connection].remove(exact[0])
        try:
            errors = [
                issue.code
                for issue in contract.validate_payload(payload)
                if issue.severity == "error"
            ]
            if errors:
                raise ValueError(
                    "machine_config_invalid: repair machine config: "
                    + ", ".join(errors)
                )
            # The general writer also seeds identity and strips retired keys.
            # Here only the selected entry may change, under its existing lock.
            machine_config_file.atomic_write_text(
                cfg, json.dumps(payload, indent=2) + "\n"
            )
        except (OSError, ValueError, RuntimeError) as exc:
            registration = _result("failed", "registration_cleanup_failed", str(exc))
        else:
            registration = _result("removed", "owned_exact_entry")
    return {
        "registration": registration,
        "trust": trust,
        "complete": registration["status"] in {"removed", "absent"}
        and all(row["status"] != "failed" for row in trust),
    }


def owning_connections(payload: dict, root: Path) -> list[str]:
    """Name every connection whose project map registers this exact checkout."""
    return [
        key
        for key, entries in contract.connection_project_maps(payload).items()
        if any(
            Path(entry["checkout"]).expanduser().resolve() == root
            for entry in normalize_projects(entries)
        )
    ]


def registration_connection(payload: dict, owners: list[str]) -> str:
    """Select the map holding this checkout's registration.

    Machine uninstall runs under whichever connection is active, and each
    universe numbers its projects from 1, so a checkout registered only on
    another connection is retired from that connection's map.
    """
    if not contract.connection_project_maps(payload):
        return ""
    selected = contract.project_connection(payload)
    return owners[0] if len(owners) == 1 and selected not in owners else selected


def _config_reason(manifest: dict, cfg: Path) -> str:
    record = manifest.get(REGISTRATION_KEY)
    return (
        "registration_config_changed"
        if isinstance(record, dict) and record.get("config") != str(cfg.resolve())
        else ""
    )


def _shared_reason(root: Path, projects: list[dict], project_id) -> str:
    if main_checkout(root) != root:
        return "linked_checkout_uses_main_registration"
    for entry in projects:
        other = Path(entry["checkout"]).expanduser().resolve()
        if other == root and entry["project_id"] != project_id:
            return "registration_project_identity_changed"
        if other != root and (
            other.is_relative_to(root)
            or root.is_relative_to(other)
            or main_checkout(other) == root
        ):
            return "registration_covers_other_checkout"
        if (
            other != root
            and cursor_trust_file(other).resolve() == cursor_trust_file(root).resolve()
        ):
            return "folder_trust_shared_with_other_checkout"
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode:
            return "worktree_identity_unavailable"
        members = [
            line[9:]
            for line in result.stdout.split("\0")
            if line.startswith("worktree ")
        ]
        if not members or any(Path(member).resolve() != root for member in members):
            return "registration_covers_git_worktrees"
    return ""


def _result(status: str, reason: str, detail: str = "", recovery: str = "") -> dict:
    return {
        "status": status,
        "reason": reason,
        "detail": detail,
        "recovery": recovery
        or "Review the exact checkout registration in machine config (`yoke projects list`); separate shared checkouts or restore the edited entry, then rerun project uninstall. Preserve credentials and other project entries.",
    }
