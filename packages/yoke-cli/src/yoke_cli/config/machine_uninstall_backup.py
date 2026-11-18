"""Uninstall backups: one archive per owned universe, named for that universe.

Each target exports to its own full path, ``local-<org>-universe-<stamp>.tar``
or ``self-host-<bundle-dir-name>-<org>-universe-<stamp>.tar``. The org slug is
only known once the export has read the universe, so the archive is written
under its label first and published under the org-bearing name from the
export report. A server whose report names no org keeps the labeled name.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import re
from pathlib import Path

from yoke_contracts.timestamps import utc_now

from yoke_cli.config import machine_uninstall_steps as steps
from yoke_cli.config.machine_uninstall_inventory import Inventory, UninstallError

_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def back_up(inventory: Inventory, emit: Callable[[str], None]) -> None:
    targets = (
        [("local universe", "local", inventory.local_env)]
        if inventory.local_universe
        else []
    )
    targets += [
        (f"self-host {directory}", f"self-host-{_safe(directory.name)}", env)
        for directory, env in inventory.bundles
    ]
    # No automatic backup and no artifact inside the home about to be deleted.
    output = Path.cwd().resolve()
    if output == inventory.home.resolve() or inventory.home.resolve() in output.parents:
        raise UninstallError(
            "uninstall_backup_inside_home: run uninstall from a directory outside "
            "the machine home so its exports survive removal."
        )
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    failures = []
    for label, prefix, env in targets:
        try:
            if not env:
                raise UninstallError(
                    "uninstall_backup_connection_missing: restore the machine connection "
                    "to this universe, then retry with --backup."
                )
            emit(f"backup {label}: done ({_export(env, output, prefix, stamp)})")
        except Exception as exc:
            failures.append(label)
            emit(f"backup {label}: failed ({type(exc).__name__}: {exc})")
    if failures:
        raise UninstallError(
            "uninstall_backup_failed: nothing was uninstalled. Repair the failed "
            "export and retry --backup, or explicitly choose --no-backup."
        )


def _export(env: str, output: Path, prefix: str, stamp: str) -> str:
    staged = _unused(output / f"{prefix}-universe-{stamp}.tar")
    stdout = steps.command(
        ["--env", env, "universe", "export", "--out", str(staged), "--json"]
    )
    try:
        report = json.loads(stdout)
    except ValueError as exc:
        raise UninstallError(
            f"uninstall_backup_report_unreadable: the export wrote {staged} but "
            f"printed no JSON report ({exc}). Check the archive, then retry --backup."
        ) from exc
    archive = Path(str(report.get("artifact") or staged))
    org = _safe(str(report.get("org") or ""))
    if org:
        final = _unused(output / f"{prefix}-{org}-universe-{stamp}.tar")
        archive = archive.rename(final)
    missing = (report.get("artifacts") or {}).get("missing")
    return f"{archive}; {missing} artifacts missing" if missing else str(archive)


def _unused(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise UninstallError(
            f"uninstall_backup_archive_exists: {path} already exists. Move it "
            "aside or run uninstall from another directory, then retry --backup."
        )
    return path


def _safe(text: str) -> str:
    return _FILENAME_UNSAFE_RE.sub("-", text).strip("-.")
