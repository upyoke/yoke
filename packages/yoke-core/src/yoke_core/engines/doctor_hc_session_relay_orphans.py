"""Doctor check for per-environment relay jobs whose machine config is gone."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import plistlib
import sys
from typing import Any

from yoke_contracts.machine_config import reader as machine_config
from yoke_contracts.machine_config.relay_instance import (
    RELAY_LABEL_PREFIX,
    RELAY_BASE_LABEL,
)
from yoke_core.engines.doctor_applicability import NOT_APPLICABLE
from yoke_core.engines import relay_orphan_supervisors as supervisors
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.domain.relay_launchd_status import RelayInstallError
from yoke_core.domain.relay_systemd_status import relay_unit_directory
from yoke_core.domain.launchctl_boundary import (
    launch_agents_dir,
    launchd_target,
    run_launchctl,
)


SLUG = "session-relay-orphans"
TITLE = "No orphaned per-environment machine relay jobs"
_LISTED_LABELS = 5


@dataclass(frozen=True)
class OrphanRelay:
    """One registered relay job whose pinned machine config is gone."""

    label: str
    plist: Path
    config_path: str


def scan_relay_login_items(
    launch_agents: Path,
) -> tuple[list[OrphanRelay], list[Path]]:
    """Split per-environment relay plists into orphans and unreadable files."""
    orphans: list[OrphanRelay] = []
    unreadable: list[Path] = []
    if not launch_agents.is_dir():
        return orphans, unreadable
    for path in sorted(launch_agents.glob(f"{RELAY_LABEL_PREFIX}*.plist")):
        try:
            with path.open("rb") as handle:
                document = plistlib.load(handle)
        except (OSError, ValueError, plistlib.InvalidFileException):
            unreadable.append(path)
            continue
        label = str(document.get("Label") or "")
        if label == RELAY_BASE_LABEL or not label.startswith(RELAY_LABEL_PREFIX):
            continue
        environment = document.get("EnvironmentVariables")
        config_path = ""
        if isinstance(environment, dict):
            config_path = str(environment.get(machine_config.CONFIG_FILE_ENV) or "")
        if config_path and Path(config_path).expanduser().is_file():
            continue
        orphans.append(OrphanRelay(label=label, plist=path, config_path=config_path))
    return orphans, unreadable


def reclaim(orphans: list[OrphanRelay]) -> list[str]:
    """Unload and delete every orphan, returning the labels reclaimed."""
    reclaimed: list[str] = []
    for orphan in orphans:
        run_launchctl(["launchctl", "bootout", launchd_target(orphan.label)])
        orphan.plist.unlink(missing_ok=True)
        reclaimed.append(orphan.label)
    return reclaimed


def _summarize(labels: list[str]) -> str:
    listed = ", ".join(labels[:_LISTED_LABELS])
    remainder = len(labels) - _LISTED_LABELS
    return f"{listed} (+{remainder} more)" if remainder > 0 else listed


def _check_native_supervisor(manager, scan, repair, args, rec) -> None:
    reclaimed = []
    problems = []
    try:
        orphans, unreadable = scan()
        if args.fix and orphans:
            for orphan in orphans:
                try:
                    if repair(orphan):
                        reclaimed.append(str(orphan))
                except (OSError, ValueError, SyntaxError, RelayInstallError) as exc:
                    problems.append(f"{orphan}: {exc}")
            orphans, unreadable = scan()
        if orphans:
            problems.append("relay jobs pin a missing machine config: " + _summarize(
                [str(orphan) for orphan in orphans]
            ))
        if unreadable:
            problems.append("unreadable relay jobs left in place: " + _summarize(unreadable))
    except (OSError, RelayInstallError) as exc:
        problems.append(str(exc))
    if problems:
        rec.record(
            SLUG, TITLE, "FAIL",
            f"{manager}: " + "; ".join(problems)
            + ". Check supervisor access and job definitions, then retry "
            "`yoke doctor run --quick --fix`.",
        )
    else:
        summary = (
            f"--fix: reclaimed {len(reclaimed)} orphan(s): {_summarize(reclaimed)}"
            if reclaimed else "no orphaned relay jobs"
        )
        rec.record(SLUG, TITLE, "PASS", f"{manager}: {summary}")


def hc_session_relay_orphans(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """HC-session-relay-orphans: no relay login item outlives its machine config."""
    if sys.platform == "win32":
        _check_native_supervisor(
            "Task Scheduler", supervisors.scan_tasks, supervisors.reclaim_task, args, rec
        )
        return
    if sys.platform == "linux":
        directory = relay_unit_directory()
        _check_native_supervisor(
            "systemd", lambda: supervisors.scan_systemd(directory),
            supervisors.reclaim_systemd, args, rec,
        )
        return
    if sys.platform != "darwin":
        rec.record(
            SLUG,
            TITLE,
            NOT_APPLICABLE,
            "no supported native relay supervisor on this platform",
        )
        return
    launch_agents = launch_agents_dir()
    orphans, unreadable = scan_relay_login_items(launch_agents)
    notes: list[str] = []
    if unreadable:
        notes.append(
            f"{len(unreadable)} unreadable relay plist(s) left in place: "
            + _summarize([path.name for path in unreadable])
        )
    if orphans and args.fix:
        reclaimed = reclaim(orphans)
        notes.append(f"--fix: unloaded and deleted {len(reclaimed)} orphan(s)")
        orphans, _ = scan_relay_login_items(launch_agents)
    if orphans:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            f"{len(orphans)} relay login item(s) in {launch_agents} pin a machine "
            f"config that no longer exists: {_summarize([o.label for o in orphans])}. "
            "Repair: `yoke doctor run --quick --fix`, which unloads and deletes "
            "exactly those jobs and never touches "
            f"{RELAY_BASE_LABEL}. macOS Login Items rows may linger until "
            "reboot or an operator-run `sudo sfltool resetbtm`."
            + ("; " + "; ".join(notes) if notes else ""),
        )
        return
    detail = f"no orphaned relay login items in {launch_agents}"
    rec.record(SLUG, TITLE, "PASS", "; ".join([detail, *notes]))


__all__ = [
    "SLUG",
    "TITLE",
    "OrphanRelay",
    "hc_session_relay_orphans",
    "reclaim",
    "scan_relay_login_items",
]
