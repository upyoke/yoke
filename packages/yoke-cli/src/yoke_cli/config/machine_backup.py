"""Machine-local portable credential backups; no control-plane dependency."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path

from yoke_contracts.machine_config.capability_secrets import (
    BROWSER_IDENTITIES_DIR_NAME,
    browser_profile_relative_path,
)
from yoke_contracts.machine_config.paths import config_path, yoke_home
from yoke_cli.config.machine_backup_files import (
    digest,
    no_symlinks,
    read_file,
    refuse,
    relative_name,
    write_changed,
)

MANIFEST = "manifest.json"
SKIP_PATTERNS = (
    "*.lock",
    "*.stale*",
    "YOKE_*_DSN_VALIDATION*",
    "yoke_validation_*.dsn",
    "github-app-user-*.json",
)


def _json(data: bytes, name: str) -> dict:
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        refuse(f"machine_backup_invalid_json: {name}")
    if not isinstance(value, dict):
        refuse(f"machine_backup_invalid_json: {name}")
    return value


def _references(config: dict):
    """Yield ``(connection name, owner, key)`` for each referenced file."""
    for env, connection in config.get("connections", {}).items():
        source = connection.get("credential_source", {})
        if source.get("kind") in {"token_file", "dsn_file"} and source.get("path"):
            yield env, source, "path"
        tunnel = connection.get("postgres", {}).get("tunnel", {})
        if tunnel.get("identity_file"):
            yield env, tunnel, "identity_file"


def _skipped(name: Path) -> bool:
    if any(
        fnmatch.fnmatch(part, pattern)
        for part in name.parts
        for pattern in SKIP_PATTERNS
    ):
        return True
    if "installer-live-tui" in name.parts:
        return True
    # Derive the browser subtree from the shared capability path contract.
    profile = browser_profile_relative_path("project")
    parts = name.parts
    for index, part in enumerate(parts):
        if part == profile.parts[-2] and index + 1 < len(parts):
            if parts[index + 1] in {profile.name, BROWSER_IDENTITIES_DIR_NAME}:
                return True
    return False


def _home_name(path: Path, home: Path) -> str:
    no_symlinks(path)
    try:
        return path.relative_to(home).as_posix()
    except ValueError:
        refuse(
            f"machine_backup_outside_home: {path.name}",
            "move the referenced file under your home and update config.json",
        )


def _reference_path(raw: str, home: Path) -> Path:
    path = Path(raw).expanduser()
    logical_home = Path.home().absolute()
    if path.is_absolute() and path.is_relative_to(logical_home):
        path = home / path.relative_to(logical_home)
    return Path(os.path.abspath(path if path.is_absolute() else home / path))


def backup(folder: Path) -> dict:
    home = Path.home().resolve()
    machine = yoke_home().expanduser()
    machine = machine.parent.resolve() / machine.name
    folder = folder.expanduser()
    folder = folder.parent.resolve() / folder.name
    no_symlinks(folder)
    if (folder / "home").exists() and not (folder / MANIFEST).is_file():
        refuse(
            "machine_backup_destination_not_backup",
            "choose an empty folder or an existing machine backup",
        )
    previous = set()
    if (folder / MANIFEST).exists():
        prior = _json(read_file(folder / MANIFEST, MANIFEST), MANIFEST)
        if prior.get("version") != 1 or not isinstance(prior.get("files"), list):
            refuse(
                "machine_backup_invalid_manifest",
                "choose an empty backup folder or repair the existing manifest",
            )
        for entry in prior["files"]:
            if not isinstance(entry, dict):
                refuse("machine_backup_invalid_manifest")
            previous.add(relative_name(entry.get("name")).as_posix())
    if folder == home or home.is_relative_to(folder) or folder.is_relative_to(machine):
        refuse(
            "machine_backup_overlapping_destination",
            "choose a separate backup folder outside the machine home",
        )
    selected = config_path()
    selected = selected.parent.resolve() / selected.name
    config_bytes = read_file(selected, "config.json")
    config = _json(config_bytes, "config.json")
    files = {_home_name(selected, home): selected}
    missing = []
    references = {}
    for tree in (machine / "secrets", machine / "ssh"):
        no_symlinks(tree)
        if not tree.exists():
            continue
        for root, dirs, names in os.walk(tree, followlinks=False):
            parent = Path(root)
            dirs[:] = [
                name
                for name in dirs
                if not _skipped((parent / name).relative_to(machine))
            ]
            for name in dirs:
                no_symlinks(parent / name)
            for name in names:
                path = parent / name
                if not _skipped(path.relative_to(machine)):
                    files[_home_name(path, home)] = path
    for env, owner, key in _references(config):
        path = _reference_path(owner[key], home)
        # A missing file has nothing to copy, so its location never refuses.
        if not path.exists() and not path.is_relative_to(home):
            missing.append(f"{path} (connection {env})")
            continue
        name = _home_name(path, home)
        references[owner[key]] = name
        if _skipped(Path(name)):
            continue
        if not path.exists():
            missing.append(f"{name} (connection {env})")
        else:
            files[name] = path
    entries, changed = [], 0
    for name, path in sorted(files.items()):
        data = config_bytes if path == selected else read_file(path, name)
        changed += write_changed(folder / "home" / name, data, boundary=folder.parent)
        entries.append(
            {
                "name": name,
                "mode": stat_mode(path),
                "size": len(data),
                "sha256": digest(data),
            }
        )
    manifest = {
        "version": 1,
        "source_home": str(home),
        "config": _home_name(selected, home),
        "files": entries,
        "missing": sorted(missing),
        "references": references,
    }
    # Remove files no longer selected, including credentials newly excluded by policy.
    payload = folder / "home"
    for name in previous - files.keys():
        path = payload / name
        no_symlinks(path)
        if path.exists():
            read_file(path, name)
            path.unlink()
    write_changed(
        folder / MANIFEST,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        boundary=folder.parent,
    )
    return {"files": len(entries), "changed": changed, "missing": sorted(missing)}


def stat_mode(path: Path) -> str:
    return format(path.stat().st_mode & 0o777, "04o")


def restore(folder: Path, *, replace: bool = False) -> dict:
    home = Path.home().resolve()
    folder = folder.expanduser()
    folder = folder.parent.resolve() / folder.name
    manifest = _json(read_file(folder / MANIFEST, MANIFEST), MANIFEST)
    entries = manifest.get("files")
    if manifest.get("version") != 1 or not isinstance(entries, list) or not entries:
        refuse(
            "machine_backup_invalid_manifest",
            "create a fresh backup with yoke machine backup",
        )
    config_name = relative_name(manifest.get("config")).as_posix()
    source_home = manifest.get("source_home")
    if not isinstance(source_home, str) or not Path(source_home).is_absolute():
        refuse("machine_backup_invalid_manifest")
    pending = {}
    for entry in entries:
        if not isinstance(entry, dict):
            refuse("machine_backup_invalid_manifest")
        name = relative_name(entry.get("name")).as_posix()
        if name in pending:
            refuse(f"machine_backup_duplicate_name: {name}")
        data = read_file(folder / "home" / name, name)
        actual, expected = digest(data), entry.get("sha256")
        if not isinstance(expected, str) or actual != expected:
            prefix = (
                expected[:12]
                if isinstance(expected, str)
                and len(expected) == 64
                and all(c in "0123456789abcdef" for c in expected)
                else "invalid"
            )
            refuse(
                f"machine_backup_hash_mismatch: {name} expected={prefix} actual={actual[:12]}",
                "recover an intact backup; do not restore this copy",
            )
        if entry.get("size") != len(data) or not isinstance(entry.get("mode"), str):
            refuse(f"machine_backup_invalid_metadata: {name}")
        pending[name] = data
    if config_name not in pending:
        refuse(f"machine_backup_missing_file: {config_name}")
    if source_home != str(home):
        config = _json(pending[config_name], config_name)
        references = manifest.get("references")
        if not isinstance(references, dict):
            refuse("machine_backup_invalid_manifest")
        changed = False
        for _env, owner, key in _references(config):
            old = Path(owner[key])
            if old.is_absolute() and owner[key] in references:
                owner[key] = str(home / relative_name(references[owner[key]]))
                changed = True
        if changed:
            pending[config_name] = (json.dumps(config, indent=2) + "\n").encode()
    # Validate the entire set before writing anything, including overwrite conflicts.
    for name, data in pending.items():
        target = home / name
        no_symlinks(target)
        for parent in target.parents:
            if parent == home:
                break
            if parent.relative_to(home).as_posix() in pending or (
                parent.exists() and not parent.is_dir()
            ):
                refuse(
                    f"machine_backup_parent_not_directory: {name}",
                    "repair the named destination parent or backup manifest, then retry",
                )
        if target.exists() and read_file(target, name) != data and not replace:
            refuse(
                f"machine_backup_existing_file_differs: {name}",
                "keep the existing file or rerun restore with --replace",
            )
    changed = sum(
        write_changed(home / name, data, boundary=home)
        for name, data in pending.items()
    )
    return {
        "files": len(pending),
        "changed": changed,
        "missing": manifest.get("missing", []),
    }
